# Cyber Range Coach v2

Локальная учебная академия. Windows-ноутбук хранит данные и подключает уже
существующие цели Docker Desktop. Отдельная Linux VM выполняет команды ученика.
Mac работает как полный браузерный клиент, телефон получает теорию, заметки,
повторения и прогресс без интерактивного терминала.

Главный контракт системы находится в [`spec.md`](spec.md), а официальные
технические источники собраны в
[`docs/official-sources.md`](docs/official-sources.md). Состояние v1 сохранено
локальной аннотированной меткой `v1-archive-b53e6dd`; проверяемая копия базы
находится в игнорируемом каталоге `backups/v1-20260820/`. Старый `start.command`
остаётся маршрутом v1 до реального Windows-пилота. После успешного пилота
канонический запуск v2 будет один:

```text
Пуск -> Cyber Range Coach
```

## Что реализовано в исходном коде v2

- FastAPI backend, SQLAlchemy, Alembic, SQLite и FTS5.
- Docker Desktop discovery только для чтения через `docker version`, `context`,
  `ps`, `inspect` и `port`.
- Подтверждаемые `TargetProfile`, создаваемые из фактических bindings контейнера.
- Временный TCP Training Relay с allowlist точного IP Linux VM и временем жизни.
- SSH host-key pinning, интерактивный терминал `student` и отдельный
  forced-command `range-runner` без общего shell.
- Проверка фактических прав `student`: lab блокируется при доступном
  non-interactive sudo или чтении/записи известных system/rootless Docker sockets.
- Детерминированный grader, обязательные объяснение, вопрос наставника,
  исправление и debrief до записи evidence. Для transcript-проверки утверждённая
  команда должна быть первой командой чистого lab run, а после эксперимента
  интерфейс создаёт новую попытку.
- Интервальные reviews с завершением старого задания и одним следующим due item.
- Пошаговый рост каждого навыка до `independent`. Для практик с Docker-целью
  доступен отдельный этап `transfer`, который требует второй fingerprint цели.
- Базовый курс из 19 практик: Linux, сеть, HTTP, authentication,
  authorization, evidence reporting и Blue/DFIR по общей трассе событий.
- Локальные методические подсказки, не влияющие на grader. Внешние AI CLI в
  Windows-релизе отключены до появления доказуемой файловой изоляции.
- Studio для content-addressed read-only snapshots DOCX, Markdown, TXT, LOG и
  изображений с SHA-256, source blocks, локальным OCR, validation и публикацией
  только владельцем. Это tamper detection, а не обещание абсолютной
  неизменяемости файловой системы.
- Одноразовое pairing Mac и телефона только после полного LAN/HTTPS preflight,
  роли `owner`, `operator`, `viewer`, ручная сверка fingerprint и CSRF-защита
  аутентифицированных изменений.
- Адаптивный React-интерфейс для ширин 360..2560 px. На телефоне терминал
  заменяется read-only transcript.
- Windows PyInstaller и Inno Setup pipeline, SHA-256 artifact, отдельные явные
  задачи доверия к CA и правила Private Firewall. Обычный quality gate собирает
  и запускает оба frozen executable, а Windows CI отдельно повторяет source smoke.

Факт: исходный код и автоматические проверки запускаются на текущем Mac.
Открытый gate: installer, DPAPI, Docker Desktop, Linux VM, Mac-клиент и телефон
ещё надо проверить на реальном оборудовании. Подробности находятся в
[`docs/acceptance-status.md`](docs/acceptance-status.md).

## Локальная разработка

Python и Node нужны только разработчику. Пользователь Windows должен получить
self-contained installer.

```bash
uv sync --extra dev
cd frontend && npm install && npm run build && cd ..
./scripts/dev.sh
```

Локальный backend открывается на `http://127.0.0.1:8443`. В development-режиме
используется локальный тестовый secret provider, потому что DPAPI доступен только
на Windows. Production installer не использует этот fallback.

## Полная проверка

```bash
./scripts/quality.sh
```

Команда запускает Ruff, mypy, backend tests, repository secret scan, ESLint,
TypeScript, Vitest, production build и Playwright на контрольных ширинах.

Windows artifact собирается только на Windows:

```powershell
.\scripts\package-windows.ps1 -PrepareOcr
```

Сценарий скачивает pinned Tesseract и языковые модели, проверяет SHA-256,
запускает gates и формирует `dist\installer\CyberRangeCoach-Setup.exe` с
соседним `.sha256`. Версии и хэши перечислены в
[`vendor/tesseract/README.md`](vendor/tesseract/README.md).

## Границы безопасности

- Discovery не запускает, не останавливает и не пересоздаёт контейнеры.
- Relay не меняет Docker и закрывается при stop, reset, timeout или остановке
  приложения.
- Firewall-скрипт требует `-Approve`, активный профиль Private и точный режим.
- Сертификат не перегенерируется, если комплект уже существует.
- SSH host key становится доверенным только после ручной сверки fingerprint.
- `range-runner` принимает только `tools`, `relay`, ограниченный `nmap` одного
  порта и ограниченный HTTP GET через relay.
- Snapshot Studio хранится read-only и проверяется по SHA-256 перед публикацией.
- Production-секреты защищаются Windows DPAPI текущего пользователя.
- Интернет-публикация, UPnP, port forwarding и облачная синхронизация отсутствуют.

## Структура

```text
backend/               FastAPI, модель данных, адаптеры, проверки и тесты
frontend/              React, адаптивный интерфейс, Vitest и Playwright
curriculum/            версионируемый детерминированный учебный материал
installer/linux/       проверенный bootstrap для student и range-runner
installer/windows/     PyInstaller, Inno Setup и скрипты Firewall
scripts/               локальная разработка и воспроизводимая упаковка
vendor/tesseract/      provenance; бинарные файлы готовятся на Windows build host
docs/                  реестр источников и инструкции по эксплуатации
```

Ни одно изменение не отправляется в GitHub без отдельного подтверждения владельца.
