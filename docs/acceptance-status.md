# Статус приёмки v2, исправления достоверности

Дата локальной проверки: 06.09.2026.
Среда: macOS, настоящий локальный backend, отдельная временная SQLite и
Chromium. Рабочая база и пользовательские данные не изменялись.

## Результат раздела 10

- AC-01 локально подтверждён структурно. Валидатор прочитал 169 из 169 условий,
  проверил публичный контекст и именованные исходные значения, приватность
  ответов, 27 источников и 2237 адресов. Адресные случаи `cat`, `grep`,
  переменной, glob и Windows-путей покрыты тестами. Полный ручной редакторский
  просмотр каждого из 169 текстов остаётся отдельной методической проверкой.
- AC-02 локально подтверждён. Значимые кавычки, экранирование, раскрытия, glob и
  операторы сохраняются консервативным lexer. Неописанная правдоподобная форма
  получает `unverified`, не штрафует и может быть исправлена в том же окне.
- AC-03 подтверждён на уровне unit/integration-контракта. Поддержаны Backspace,
  Delete, Left/Right, Home/End, Ctrl+A/E/U/K/C и разорванные escape-sequences.
  Tab, неизвестная или многострочная история, reconnect, обрезание transcript и
  неподтверждённый временный Bash-профиль закрываются как `unverified`.
  Фактический PTY/SSH, намеренно изменённый vi-mode и все 19 уроков на реальной
  VM ещё не проверены.
- AC-04 локально подтверждён. Все 169 разборов вывода и семь вариантов миссий
  используют обязательные структурированные факты. Свободное объяснение
  сохраняется со статусом `not_assessed` и само не может дать `solved`.
- AC-05 локально подтверждён на серверном и API-уровне. Подсказки и явное
  раскрытие карточки создают идемпотентное help-событие, которое действует для
  новых ключей и связанных поверхностей. Проверка на втором реальном устройстве
  остаётся открытой.
- AC-06 локально подтверждён. Сервер создаёт окно assessment/rehearsal, вводит
  24-часовой срок выдержки после помощи или ошибки, не двигает интервал при
  rehearsal/unverified и применяет продвижение один раз. Две независимые
  database sessions с разными ключами используют одно окно и дают только одно
  продвижение.
- AC-07 локально подтверждён на копии. Миграция `20260906_0005` сохраняет старые
  command attempts, mission runs и интервалы, добавляет нейтральные версии
  политики и проходит upgrade, downgrade и `PRAGMA integrity_check`. К рабочей
  базе миграция не применялась. Windows остаётся `awaiting_stand`.
- AC-08 частично закрыт. `scripts/quality.sh` прошёл целиком после последней
  правки: Ruff, mypy, 96 pytest, оба контент-валидатора, secret scan, shell
  syntax, 10 Vitest, production build, frozen PyInstaller/Alembic smoke и 17
  Playwright. Независимый `critic-code` в этой сессии не запускался.
- AC-09 частично закрыт живым UI. На настоящем backend и временной базе пройден
  путь 390 px `подсказка -> команда -> отдельный структурированный разбор`;
  результат после помощи не увеличил интервал. На 390 и 1366 px горизонтального
  переполнения нет, публичный контекст и поля фактов видимы, browser console
  чиста. Полная матрица wrong/save/reload/back/due на настоящем backend, а также
  реальный телефон ещё открыты. Mock-based Playwright отдельно сохранил прежние
  девять контрольных ширин.

Итог: реализация раздела 10 локально проверена. Производственная и полигонная
готовность не заявляются до закрытия реальных Windows, SSH/VM, второго устройства,
полной живой UI-матрицы и независимого review.

## Историческая база до исправлений

Дата локальной проверки: 21.08.2026.
Среда локальной разработки: macOS. Реальный Windows hardware в этой сессии
недоступен, Windows source и installer smoke выполнены на GitHub runner
`windows-latest`.

## Подтверждено автоматически

- Ruff и mypy проходят для backend source.
- 48 backend tests проходят, включая negative security tests для CSRF, pairing
  до полного HTTPS preflight,
  конкурентного запуска lab, Docker discovery, grader, evidence lifecycle,
  type-ahead между shell-командами, relay TTL, Studio snapshots, migrations,
  redaction, зафиксированного списка Linux tools,
  активного Private profile, single-instance process lock и range-runner command
  allowlist.
- Чистая SQLite database создаётся frozen Alembic revision `20260820_0001`;
  runtime подтверждает revision, FTS5 и `PRAGMA integrity_check`.
- Repository secret scan проходит.
- ESLint и TypeScript проходят.
- 7 Vitest tests проходят, включая безопасный LAN origin, полный HTTPS-preflight
  gate для pairing QR и fail-closed отображение отсутствующих runner tools.
- Production frontend build проходит.
- PyInstaller собирает два разных frozen executable на development host и на
  GitHub runner `windows-latest`. Основной `CyberRangeCoach` и отдельный
  консольный `CyberRangeCoachDoctor` собираются, их `--help` завершаются успешно.
  Локальный read-only Doctor preflight также проходит.
- GitHub run `32444908652` собирает `CyberRangeCoach-Setup.exe` с закреплённым
  OCR, создаёт SHA-256, выполняет тихую установку без необязательных задач,
  запускает установленный executable, удаляет приложение и загружает artifact.
  Это не заменяет установку на реальном Windows-компьютере пользователя.
- 16 Playwright tests проходят в Chromium:
  - responsive shell на 360, 390, 480, 768, 1024, 1366, 1440, 1920 и 2560 px;
  - touch targets и keyboard focus;
  - mobile/tablet read-only transcript;
  - terminal resize на desktop;
  - Studio editor на mobile и desktop;
  - восстановление сохранённой LearningSession после reload;
  - autosave полевой заметки.
- `bash -n` проходит для Linux bootstrap, forced-command checker и пяти shell scripts.
- `git diff --check` проходит.
- Четыре сохранённых v1 regression gates проходят.

Числа выше являются адресными результатами `scripts/quality.sh`, backend test
collection, `frontend/e2e/responsive.spec.ts` и legacy quality scripts. Если test
collection изменится, этот файл надо обновить только после нового успешного run.

## Реальные gates, которые ещё не подтверждены

- Запуск установщика на реальном Windows x64 пользователя.
- Запуск приложения из меню Пуск без отдельно установленных Python, Node.js и Git.
- Windows DPAPI в обычном user context после UAC installer.
- Локальный CA, certificate SAN и Private-only Firewall в реальной системе.
- Read-only discovery фактически работающих Docker Desktop containers.
- Проверка, что Docker containers и volumes не изменились после установки.
- Реальные `0.0.0.0` warnings для текущих bindings пользователя.
- SSH authentication, host-key pinning и `student` boundary в фактической Linux VM.
- Forced-command `range-runner` и отрицательная arbitrary-command проверка в VM.
- Маршрут `Linux VM -> Training Relay -> выбранный Docker target`.
- Stop, reset, TTL и application shutdown для relay на Windows.
- Pairing, certificate trust и layout на фактическом Mac и телефоне.
- Bundled Tesseract OCR на Windows.
- Windows installer uninstall/rollback без удаления `%LOCALAPPDATA%` данных.

External Codex CLI и Claude Code не являются открытым gate: для Windows v2 они
отключены по проектному решению. Методические подсказки и grader работают локально.

До закрытия hardware gates v1 `start.command` остаётся прежним каноническим
маршрутом. Переключение на `Пуск -> Cyber Range Coach` допустимо только после
реального пилота и повторного полного quality run.
