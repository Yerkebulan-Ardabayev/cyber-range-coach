# Cyber Range Coach v1 baseline

Дата фиксации: 2026-08-20.

- Commit: `b53e6ddb0fae494d0b9b1c281a3d765c897eea14`
- Локальная annotated tag: `v1-archive-b53e6dd`
- Исходная база: `state.sqlite`
- Резервная копия: `backups/v1-20260820/state.sqlite`
- SHA-256 базы и копии: `fcddd3987319eb2c7943556843310857900410a4c32bba5f1f985b9beb8c1689`
- SQLite integrity check: `ok`
- Notes: `2`
- Attempts: `12`

Перед началом v2 успешно прошли:

- `python3 tools/validate_content.py`
- `python3 tools/test_mentor.py`
- `python3 tools/test_learning_flow.py`
- `node tools/test_learning_view.mjs`
- `python3 -m py_compile server.py parsers/__init__.py`
- `node --check web/app.js`
- `node --check web/learning-view.js`
- `git diff --check`

Резервная копия исключена из Git. Она предназначена только для локального
восстановления и экспорта двух Field Notes.
