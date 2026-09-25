<context>
Ты на Windows-ноутбуке-полигоне Cyber Range Coach. Правила машины в `%USERPROFILE%\.claude\CLAUDE.md`, правила проекта в `CLAUDE.md` репозитория. Прошлый отчёт `docs/noutbuk/otchety/20260925-1419.md`: мастер WSL встал на ложной проверке sudo в `bootstrap-linux.sh`.

Что сделано на Mac 25.09 по отчёту:
- `installer/linux/bootstrap-linux.sh`: правило sudo определяется по тексту ответа `sudo -l -U`, а не по коду возврата (sudo 1.9.15p5 отдаёт 0 и для «is not allowed»). Проверено тестом в Ubuntu 24.04 с тем же sudo.
- При чужом пользователе `student` скрипт подсказывает команду передачи `sudo usermod -c 'Cyber Range Coach' student`.
- Путь моста в `CLAUDE.md` исправлен на `%USERPROFILE%\vault-bridge-mac`.
- Для ноутбука появилась команда `/zapomni`: `docs/noutbuk/skills/zapomni/SKILL.md`.
- Новый установщик собирается в GitHub Actions. Ссылку на него Mac кладёт в этот файл, раздел «Установщик».
</context>

<instructions>
1. Скопируй `docs/noutbuk/skills/zapomni/SKILL.md` в `%USERPROFILE%\.claude\skills\zapomni\SKILL.md` (создай папки). Исправь путь моста в `%USERPROFILE%\.claude\CLAUDE.md`, если там стоит `Documents`. Проверь в новой сессии, что `/zapomni` виден.
2. Установщик. Если в разделе «Установщик» ниже есть ссылка, скачай его, сверь SHA-256, поставь поверх старого (данные академии сохраняются) и перезапусти академию. Если ссылки нет, скажи владельцу, что установщик ещё собирается, и остановись.
3. «Система» → «Подготовить WSL Ubuntu» → команда в Ubuntu (sudo-пароль вводит владелец). `student` уже помечен, повторно не менять.
4. Пройди оставшиеся шаги мастера (SSH, отпечаток ключа, runner-check), затем урок «TCP-достижимость учебной цели» с Juice Shop.
5. Отчёт в `docs/noutbuk/otchety/<ГГГГММДД-ЧЧММ>.md`, коммит по имени, push.
</instructions>

<constraints>
- Код академии на ноутбуке не править, ошибки описывать в отчёте.
- Docker, брандмауэр, `.wslconfig`, контролируемый доступ к папкам не менять без «да» владельца.
- Пароли вводит только владелец.
</constraints>

## Установщик

Готов: сборка `6ec891a`, GitHub Actions run `36119130173`, артефакт `CyberRangeCoach-Windows-unsigned` (около 106 МБ).
SHA-256 `CyberRangeCoach-Setup.exe`: `bea3bb977551e952ee84006bbea5f20d1d3eb04d0cfcbb810606efe6b2c20ca9`.

Как скачать. Артефакт скачивается только после входа в GitHub:
- Способ 1: если есть `gh` (иначе спроси владельца и после «да» поставь `winget install --id GitHub.cli -e`, вход `gh auth login --web` делает владелец), выполни `gh run download 36119130173 -R Yerkebulan-Ardabayev/cyber-range-coach -n CyberRangeCoach-Windows-unsigned -D %USERPROFILE%\crc-installer-6ec891a`.
- Способ 2: открой владельцу страницу https://github.com/Yerkebulan-Ardabayev/cyber-range-coach/actions/runs/36119130173, он нажмёт на артефакт внизу страницы, затем распакуй zip из «Загрузок».
Перед установкой сверь SHA-256 (`Get-FileHash`), не совпало → не ставить.
