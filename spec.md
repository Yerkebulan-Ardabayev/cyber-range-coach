# Cyber Range Coach v2

Статус: утверждён пользователем 20.08.2026, реализация проходит локальную
проверку, реальные device-gates ещё открыты.

Этот документ является каноническим контрактом v2. Версия v1 сохранена локальной
аннотированной меткой `v1-archive-b53e6dd`, а её база сохранена в непубликуемом
каталоге `backups/v1-20260820/`. Старый код остаётся только маршрутом отката до
успешного Windows-пилота.

## 1. Цель

Создать локальную интерактивную академию кибербезопасности для одного владельца.
Сервер и база работают на Windows-ноутбуке, существующие учебные контейнеры
Docker Desktop остаются целями, а команды ученика выполняются в отдельной Linux
VM. Проверка результата детерминирована и не зависит от AI.

Главная единица обучения представляет доказанный цикл:

```text
термин -> пример -> прогноз -> действие -> наблюдение -> объяснение
-> вопрос наставника -> исправление и debrief -> evidence -> повторение
```

Навык меняет состояние только после полного цикла и может дойти до
`independent`. Этап `transfer` применяется только к навыкам с Docker-целями и
требует успешного повтора на второй цели с другим fingerprint.

## 2. Части системы

| Часть | Назначение |
|---|---|
| Windows host | Единственный сервер, основная база, Studio и точка доступа по домашней сети. |
| FastAPI backend | API, роли устройств, сессии, graders, Docker discovery, relay, SSH terminal, импорт и поиск. |
| React frontend | Адаптивная академия для Windows, Mac, планшета и телефона. |
| SQLite + FTS5 | Курсы, сессии, evidence, reviews, устройства, targets, заметки и поиск. |
| Docker Desktop adapter | Только читает состояние существующих контейнеров и опубликованные порты. |
| Training Relay | Временно проксирует TCP от точного IP Linux VM к loopback-порту выбранного контейнера. |
| SSH adapter | Открывает shell `student` и строго ограниченные probes `range-runner`. |
| Deterministic grader | Проверяет зарегистрированную команду и структурированное наблюдение. |
| Методический наставник | Возвращает локальный сократический вопрос по фактам run, не влияет на verdict. |
| Studio | Создаёт content-addressed read-only snapshot, source blocks и проверяемый черновик. |
| Windows packaging | Формирует self-contained installer приложения и doctor. |

Внешние Codex CLI и Claude Code не входят в активный Windows-релиз. Исходный код
экспериментальных adapters сохраняется за выключенным флагом, но Windows всегда
отклоняет их запуск, потому что текущая модель изоляции не доказывает отсутствие
чтения других локальных файлов.

## 3. Контракты компонентов

### Backend API

- Вход: JSON API, multipart imports, WebSocket terminal, curriculum files и SQLite.
- Выход: JSON, WebSocket frames и статический production frontend.
- Аутентифицированные изменяющие операции требуют разрешённую роль и CSRF token.
- Единственное исключение по CSRF: первичное `POST /devices/pair`, где ещё нет
  сессии. Оно требует одноразовый 10-минутный secret и точный fingerprint.
- Pairing secret потребляется атомарно; параллельный второй запрос отклоняется.
- Ошибки имеют структуру `{code, message, details, trace_id}` без секретов.

### Docker Desktop adapter

- Вход: `docker version`, `docker context inspect`, `docker ps`,
  `docker inspect` и `docker port` с timeout.
- Выход: нормализованные `DiscoveredTarget[]`.
- Adapter не выполняет `run`, `start`, `stop`, `restart`, `rm`,
  `compose up/down`, pull, удаление volume или изменение Docker settings.
- TCP Docker daemon на `2375` не включается.

### Training Relay

- Вход: подтверждённый `TargetProfile`, точный IP Linux VM и свободный порт из
  диапазона `47000..47100`.
- Выход: временный relay endpoint и lifecycle state.
- Relay принимает TCP только от указанного IP Linux VM.
- Назначение всегда берётся из подтверждённого loopback endpoint target profile.
- Relay закрывается при stop, reset, TTL или остановке приложения.

### SSH terminal и range-runner

- Интерактивный shell открывается только для `student` с закреплённым SSH host key.
- Bootstrap от root отклоняет любую запись `student` в полном sudo policy. Перед
  lab backend повторно отклоняет доступный `sudo -n -l`, `sudo -n true` и чтение
  или запись известных system/rootless Docker sockets.
- Один lab run имеет не более одной активной terminal session.
- Backend регистрирует отправленные terminal commands отдельно от transcript.
- `range-runner` не получает общего shell, PTY или forwarding. Он принимает
  `tools`, TCP probe relay, `nmap -sV -Pn` одного разрешённого порта и HTTP GET
  через relay. Host и port не берутся из curriculum в обход профиля.
- HTTP probe возвращает только структурированные метод, path, status и наличие
  заголовка. Body, cookie, token и значение заголовка не возвращаются grader.

### Deterministic grader и evidence

- Grader получает lesson specification, зарегистрированные commands,
  структурированное probe-наблюдение, target fingerprint и артефакты текущего run.
- Результат observation gate: `passed|failed|needs_evidence` с адресными причинами.
- Текст transcript сам по себе не доказывает факт. Поддельный `printf` не проходит
  target probe и не создаёт evidence.
- После observation pass ученик обязан сохранить объяснение, получить локальный
  вопрос наставника и записать исправление/debrief.
- Только `POST /lab-runs/{id}/finalize` создаёт evidence и завершает run.
- Повторный finalize того же run не создаёт дубликат evidence или review.
- Завершённый due review закрывается; создаётся или обновляется один следующий.
- Каждый успешный evidence продвигает skill не более чем на одну ступень.
- `transfer` разрешён только для target-backed навыка, из `independent` и при
  двух разных fingerprints. Практики только в Linux VM завершают рост на
  `independent`.
- Любой AI-ответ исключён из входов grader и не может изменить verdict.

### Studio

- Вход: DOCX, MD, TXT, LOG, PNG, JPEG или TIFF.
- Выход: content-addressed snapshot, SHA-256, source blocks, deterministic draft
  и validation report.
- Исходный пользовательский файл не редактируется.
- Snapshot переводится в read-only mode и повторно проверяется по SHA-256 перед
  публикацией. Это обнаруживает изменение, но не заявляет аппаратную immutable FS.
- OCR выполняется локально. Публикацию выполняет только `owner`.
- AI-generated draft в первой Windows-версии не используется.

## 4. Данные

### Файлы под Git

- `curriculum/`: tracks, modules, lessons, skills, graders и reviews.
- `frontend/`: React и TypeScript.
- `backend/`: FastAPI и frozen Alembic operations.
- `installer/`: Windows packaging и Linux bootstrap, ничего не запускается
  автоматически из репозитория.

### Windows application data

```text
%LOCALAPPDATA%\CyberRangeCoach\
  data\academy.db
  content\
  imports\
  backups\
  logs\
  certificates\
  runtime\
```

### Основные сущности

- `Device`: роль `owner|operator|viewer`, token hash, timestamps, revoke state.
- `PairingCode`: one-time token hash, requested role, expiry, consumed state.
- `TargetProfile`: provider, container reference, digest, host endpoint,
  relay policy, fingerprint и approved tags.
- `LinuxHost`: host, port, usernames, pinned fingerprint, encrypted key refs.
- `LearningSession`: duration `15|45|90`, planned lessons, status и timestamps.
- `LabRun`: lesson, target, terminal inputs, transcript, observation verdict,
  explanation, tutor timestamp, correction, start и completion state.
- `Evidence`: skill, stage, run, target fingerprint, fact и grader decision.
- `ReviewItem`: skill, lesson, due date, причина повторения и completion.
- `SkillState`: `introduced|guided|independent|transfer`, due date и history.
- `Note`: lesson, run, body, source v1 id и source hash.
- `StudioSource`: stored path, original name, media type, SHA-256, timestamps.
- `SourceBlock`: source id, ordinal, page/paragraph reference, extracted text.
- `Draft`: source coverage, `draft|validated|published`, content.

На Windows приватные ключи и локальные secrets защищаются DPAPI для текущего
пользователя. Development fallback явно маркируется и не допускается installer.

## 5. Сценарии

### Первый запуск на Windows

Пользователь устанавливает приложение. Doctor проверяет Windows, Docker, сеть,
SQLite и Linux VM. Discovery только читает контейнеры. Owner подтверждает target
profile. Backend проверяет loopback endpoint, SSH boundary и маршрут
`Linux VM -> relay -> target`. Lab остаётся заблокированным, пока эти проверки
не пройдут.

### Учебная сессия

Пользователь выбирает 15, 45 или 90 минут. Backend заполняет этот timebox суммой
оценочных длительностей уроков, сохраняет план и связанную
`LearningSession`. Страница урока переиспользует эту session. Ученик делает
прогноз и вводит утверждённую команду первой командой чистого lab run. После
эксперимента явный reset создаёт новый run. Ученик проходит observation gate, объясняет факт, получает
сократический вопрос, записывает исправление и debrief. После finalize создаются
evidence и следующий review. Session получает `completed`, когда завершены все
уроки плана. Девяностоминутный план завершает маршрут evidence-report уроком, но
сам по себе не обещает `transfer`.

### Доступ с Mac и телефона

Только после полного LAN/HTTPS preflight owner создаёт token, который живёт
10 минут. QR содержит только token. Пользователь
отдельно сверяет certificate fingerprint с Windows-экраном и вводит его вручную.
После атомарного потребления token Mac получает выбранную роль, телефон обычно
получает `viewer`. Viewer не может вводить terminal commands, запускать lab,
управлять relay/Docker, публиковать Studio draft или менять system settings.

### Studio

Owner импортирует файл. Backend копирует его, пишет SHA-256, извлекает source
blocks и переводит snapshot в read-only mode. Deterministic template создаёт
draft. Validator проверяет hash, read-only state, покрытие и ссылки. Owner вручную
публикует новую версию. Пользовательский оригинал не меняется.

## 6. Не-цели первой версии v2

- Интернет-публикация, UPnP, port forwarding, Tailscale и cloud sync.
- Вторая активная база на Mac.
- Ввод terminal с телефона.
- Произвольный PowerShell, административный shell или Docker socket.
- AI-команды, AI-grading, AI-draft и AI-autopublish.
- Автоматическое управление lifecycle пользовательских Docker-контейнеров.
- Автоматическая перестройка ручного DOCX.
- Multi-user организация, оплата, рейтинг или публичный CTF.
- Автоматические действия против внешних доменов.

## 7. Действия, требующие владельца

- Доступ к Windows-ноутбуку и запущенной Linux VM для реального preflight.
- Запуск installer, доверие локальному CA и правило Windows Firewall.
- Установка OpenSSH server в Linux VM, только если он отсутствует.
- Логин или установка внешнего AI CLI не требуются для Windows v2.
- Git push выполняется только после отдельного подтверждения.
- Любое изменение контейнеров, Compose, volumes или bindings требует отдельного
  решения и не входит в discovery.

## 8. Готово, когда

1. Backend и frontend собираются, типизируются и проходят tests.
2. Чистая база, FTS5 virtual tables и triggers создаются frozen Alembic migration;
   downgrade удаляет всю application schema, runtime подтверждает revision и integrity.
3. Docker discovery распознаёт published ports и предупреждает о `0.0.0.0`, не
   выполняя mutating Docker command.
4. Relay принимает только точный IP Linux VM и закрывается при stop, reset, TTL
   и shutdown.
5. SSH terminal поддерживает input, output, resize, reconnect и transcript.
6. Lab блокируется при unsafe `student` sudo/Docker boundary.
7. `range-runner` отклоняет произвольную shell command и не раскрывает body/secrets.
8. Viewer получает 403 на terminal input, relay, lab mutations и Studio publish.
9. Для transcript-grader approved command должна быть первой shell-командой нового
   lab run. Gateway фиксирует ledger и input offset, поэтому вывод более раннего
   процесса не может попасть в зачётную попытку. После любой пробной команды ученик
   запускает явную чистую попытку. Evidence появляется только после explanation,
   tutor question и correction/debrief.
10. `transfer` нельзя получить на том же target fingerprint или прямым прыжком.
11. Ошибка TCP/HTTP не описывается как полученный HTTP response.
12. Review закрывается после успешного повторения, без вечных дубликатов.
13. Studio сохраняет original SHA-256, обнаруживает mutation и не публикует без owner.
14. Внешний AI на Windows fail-closed и не является обязательной зависимостью.
15. Нет page overflow на 360, 390, 480, 768, 1024, 1366, 1440, 1920 и 2560 px.
16. Windows package запускается без отдельно установленных Python, Node.js и Git.
17. Реальный пилот подтверждает Windows -> Docker, Windows -> Linux SSH,
   Linux VM -> relay -> Docker, Mac -> academy и phone viewer.
18. v1 восстанавливается по tag/backup; в v2 импортируются только Field Notes с
   source id и source hash.

Фактический статус каждого gate ведётся в
[`docs/acceptance-status.md`](docs/acceptance-status.md). Официальные основания
технических утверждений находятся в
[`docs/official-sources.md`](docs/official-sources.md).
