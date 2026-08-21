# Cyber Range Coach: навигатор

1. [`README.md`](README.md): текущее состояние, запуск, проверки и безопасность.
2. [`spec.md`](spec.md): канонический контракт v2 и acceptance gates.
3. [`docs/windows-installation.md`](docs/windows-installation.md): установка на Windows.
4. [`docs/linux-vm-setup.md`](docs/linux-vm-setup.md): подключение Linux VM.
5. [`docs/official-sources.md`](docs/official-sources.md): официальные основания сетевой, SSH, HTTP, OCR и privacy-модели.
6. [`docs/v1-baseline.md`](docs/v1-baseline.md): зафиксированное состояние v1.
7. [`docs/acceptance-status.md`](docs/acceptance-status.md): что проверено автоматически и какие реальные device-gates ещё открыты.

Исходный код v2 находится в `backend/`, `frontend/`, `curriculum/` и `installer/`.
Старые `server.py`, `web/`, `content/` и `start.command` принадлежат сохранённой v1.
Они не являются второй активной реализацией и будут сняты с канонического маршрута
только после Windows, Linux VM, Mac и phone acceptance.
