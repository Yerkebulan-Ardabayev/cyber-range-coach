<context>
Ты работаешь на Windows-ноутбуке владельца (профиль `C:\Users\PC`). Владелец ведёт проект Cyber Range Coach на двух машинах: Mac (код, тесты) и этот ноутбук (установленная академия, Docker-мишени, WSL Ubuntu, живые проверки). Нужно, чтобы ты видел всё, что делается на Mac, и сам отправлял туда результаты.

Два канала связи:
1. Репозиторий проекта `https://github.com/Yerkebulan-Ardabayev/cyber-range-coach` (публичный). В нём правила `CLAUDE.md`, состояние работ `goal.md`, текущее задание `docs/noutbuk/ZADANIE.md`, папка отчётов `docs/noutbuk/otchety/`.
2. Мост памяти. Память Obsidian владельца живёт на Mac в приватном репозитории `https://github.com/Yerkebulan-Ardabayev/obsidian-vault-mac`. На этот ноутбук из неё нужны только 5 файлов этого проекта. Остальные проекты сюда попадать не должны.

Прошлое задание ссылалось на мост с другой машины. На этом ноутбуке его нет, это нормально: здесь мост создаётся заново.
</context>

<instructions>
Выполни один раз, по порядку.

1. Проверь, есть ли `git`. Если нет, спроси владельца и после его «да» поставь `winget install --id Git.Git -e`.
2. Создай мост памяти. Команды для PowerShell:
   ```
   cd $env:USERPROFILE\Documents
   git clone --filter=blob:none --no-checkout --sparse https://github.com/Yerkebulan-Ardabayev/obsidian-vault-mac.git vault-bridge-mac
   cd vault-bridge-mac
   git sparse-checkout set --no-cone memory/project_cyber-range-coach.md memory/reference_windows_laptop.md knowledge/cybersecurity/cyber-range-coach-learning-flow.md knowledge/netacad/cyber-range-coach-windows-firewall-lan-access.md knowledge/code/cyber-range-coach-stage2-stage3a-validation.md
   git checkout main
   ```
   Репозиторий приватный, поэтому Git откроет окно входа в GitHub. Скажи владельцу, что в этом окне нужно войти в свой GitHub, и жди. Готово, когда в папке моста ровно эти 5 файлов (на Mac эта команда проверена, скачивается около 0,6 МБ).
3. Склонируй репозиторий проекта:
   ```
   cd $env:USERPROFILE
   mkdir Projects -Force
   git clone https://github.com/Yerkebulan-Ardabayev/cyber-range-coach.git Projects\cyber-range-coach
   ```
4. Прочитай `Projects\cyber-range-coach\CLAUDE.md`, `goal.md` и карточку `Documents\vault-bridge-mac\memory\project_cyber-range-coach.md`. В `CLAUDE.md` описано, как работает «запомни» на этой машине.
5. Этот ноутбук служит только полигоном для Cyber Range Coach, других проектов на нём нет. Настрой Claude Code на нём так:
   - В `%USERPROFILE%\.claude\CLAUDE.md` (создай, если нет) запиши: машина только для Cyber Range Coach; проект в `%USERPROFILE%\Projects\cyber-range-coach`, правила в его `CLAUDE.md`; память проекта, общая с Mac, это мост `%USERPROFILE%\Documents\vault-bridge-mac`; «запомни» = раздел `## Update <дата> [windows]` в `memory/project_cyber-range-coach.md` моста, затем `git add` этого файла по имени, `git commit`, `git push`; в конце каждой работы отчёт в `docs/noutbuk/otchety/` проекта и `git push`, чтобы Mac получил результат.
   - Добавь в `%USERPROFILE%\.claude\settings.json` хук `SessionStart`, который в начале каждой сессии делает `git pull` в проекте и в мосте, чтобы всё новое с Mac приходило само. Остальные настройки в файле не трогай. Проверь хук: открой новую сессию и убедись, что pull прошёл без ошибок.
6. Выполни `docs/noutbuk/ZADANIE.md` из репозитория проекта.
</instructions>

<constraints>
- В мосте только 5 файлов выше. Список не расширять, `git sparse-checkout disable` не запускать.
- В мосте коммитить только файлы проекта и добавлять их по имени, без `git add -A`.
- Пароли вводит только владелец. Их не спрашивать в чате и не записывать.
- Ничего не удалять.
</constraints>

<output>
Владельцу пиши по-русски, коротко и простыми словами, одно действие за раз. В конце перечисли, что изменилось на ноутбуке: где лежат мост и проект, что дописано в `CLAUDE.md`.
</output>
