---
name: zapomni
description: Сохранить состояние проекта Cyber Range Coach в общую с Mac память (мост vault-bridge-mac) и отправить её на Mac. Триггеры /zapomni, /запомни, «запомни», «сохрани в память», «в лог».
---

# /zapomni на Windows-ноутбуке

Эта машина служит только полигоном Cyber Range Coach. Память проекта общая с Mac и лежит
в мосте `%USERPROFILE%\vault-bridge-mac`, файл `memory\project_cyber-range-coach.md`.

1. `git pull --rebase` в мосте. Затем прочитать карточку целиком.
2. Дописать в конец раздел `## Update <ГГГГ-ММ-ДД> [windows]: <о чём>`:
   - `[S]` что сделано и проверено, с путями, коммитами и точным текстом ошибок;
   - решения владельца;
   - `### Уроки <дата> [windows]`, только новые;
   - `### TODO <дата> [windows]`, чекбоксы, что делает Mac и что ноутбук.
   Старое не удалять и не переписывать. Во frontmatter обновить `updated:` и строку
   `description:` (статус и следующий шаг, одна строка).
3. В мосте `git add memory/project_cyber-range-coach.md`, `git commit -m "[windows] Cyber Range Coach: память <дата>"`, `git push`.
   Отказ push из-за новых коммитов с Mac: `git pull --rebase`, затем снова `git push`.
4. Если в проекте `%USERPROFILE%\Projects\cyber-range-coach` есть незакоммиченный отчёт в
   `docs\noutbuk\otchety\`, закоммитить его по имени и сделать `git push`.
5. Ответить владельцу коротко по-русски: что сохранено (2-3 пункта) и что всё отправлено на Mac.

Паролей, ключей и токенов в память не писать. Другие файлы моста не трогать.
