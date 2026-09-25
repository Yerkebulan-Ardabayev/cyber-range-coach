# Установка Cyber Range Coach на Windows

Статус инструкции: сценарии и installer source реализованы, но этот маршрут ещё
не прошёл smoke на Windows-ноутбуке пользователя. До такого теста команды ниже
являются процедурой приёмки, а не утверждением об уже выполненной установке.

## Что не надо переустанавливать

Docker Desktop, WebGoat, Juice Shop, images, volumes и Compose-файлы оставьте как
есть. Академия обнаруживает опубликованные порты существующих контейнеров и не
управляет их lifecycle.

Пользовательский installer должен включать Python runtime, backend, собранный
frontend, SQLite migrations, локальный OCR runtime и doctor. Node.js, npm, Git,
Python и отдельная база на целевой Windows-машине не требуются.

## Условия перед пилотом

1. Windows 10 или 11 x64.
2. Docker Desktop запущен в режиме Linux containers.
3. Linux VM запущена и имеет отдельный LAN IPv4.
4. Для доступа Mac/телефона активная домашняя сеть Windows имеет профиль `Private`.
5. Собранный `CyberRangeCoach-Setup.exe` и соседний `.sha256` получены из одного
   Windows build run.

## Установка и отдельные согласия

1. Сверьте SHA-256 installer с соседним `.sha256`.
2. Запустите installer.
3. Просмотрите необязательную задачу доверия локальному CA в хранилище текущего
   Windows-пользователя.
4. Отдельно просмотрите правило входящего TCP 8443 только для `Private` и
   `LocalSubnet`.
5. Завершите установку и откройте один маршрут: `Пуск -> Cyber Range Coach`.

UAC используется для копирования файлов и Firewall. Генерация user-bound secrets,
доверие пользовательскому CA и первый запуск выполняются в исходном пользовательском
контексте. CA path вычисляет сам `CyberRangeCoach.exe` из `%LOCALAPPDATA%` этого
процесса, а не elevated Inno Setup. Это важно для Windows DPAPI и отдельной
admin-учётной записи UAC.

Ожидаемая раскладка после успешного installer smoke:

```text
C:\Program Files\Cyber Range Coach\
%LOCALAPPDATA%\CyberRangeCoach\
```

Удаление программы не должно удалять базу, imports, заметки, backups и certificates
из `%LOCALAPPDATA%`. Это отдельный Windows acceptance gate.

## Первый preflight

В `Система` doctor и backend выполняют read-only диагностику:

- Docker CLI и Engine доступны;
- фактические containers, images, digests, health и published bindings прочитаны;
- `0.0.0.0`/LAN exposure помечен предупреждением;
- target доступен на loopback Windows;
- Linux VM принимает SSH key с подтверждённым host fingerprint;
- `student` фактически не имеет passwordless sudo и доступа к известным Docker sockets;
- `range-runner` возвращает ожидаемый protocol marker и подтверждает каждый
  обязательный инструмент текущего курса;
- Linux VM видит выбранный target только через временный relay.

Lab run не стартует без подтверждённого LinuxHost, безопасной boundary-проверки
`student`, полного набора инструментов курса и, для Docker lesson, успешного
ограниченного target probe. Preflight не устанавливает OpenSSH, не меняет Compose
и не перезапускает контейнер.

Если Windows получила новый LAN IPv4, который не входит в certificate SAN, LAN
mode должен остановиться. После ручной сверки адреса владелец отдельно запускает:

```powershell
CyberRangeCoach.exe setup --generate-certificate --force-certificate
```

Затем публичный CA снова устанавливается в доверенные для текущего пользователя.

## Mac и телефон

Owner создаёт pairing ticket на 10 минут. QR содержит только одноразовый token,
но не certificate fingerprint. На втором устройстве:

1. Откройте показанный `https://<windows-ip>:8443`.
2. Установите доверие только к CA, скачанному непосредственно с Windows academy.
3. Сравните SHA-256 certificate fingerprint с экраном Windows символ в символ.
4. Отсканируйте QR или перенесите token.
5. Введите fingerprint вручную и завершите pairing.

Token потребляется один раз. Mac получает `operator` только если owner выбрал эту
роль. Телефон оставляйте `viewer`. Сессию устройства можно отозвать в `Система`.

## Firewall и откат

Installer может создать только UI rule TCP 8443 для Private LAN. Relay rule
создаётся один раз и привязан к виртуальному адаптеру WSL, а не к адресу WSL:
адрес меняется при каждой перезагрузке, академия берёт его сама при каждом
запуске relay (урока с целью) и при необходимости сама запускает Ubuntu. Права администратора нужны только для этой команды:

```powershell
powershell -NoProfile -File "C:\Program Files\Cyber Range Coach\tools\configure-firewall.ps1" `
  -Mode Relay `
  -ApplicationPath "C:\Program Files\Cyber Range Coach\CyberRangeCoach.exe" `
  -Approve
```

Скрипт должен отказать при отсутствии активного Private profile. Откат удаляет
только rules группы `Cyber Range Coach`:

```powershell
powershell -NoProfile -File "C:\Program Files\Cyber Range Coach\tools\remove-firewall.ps1" -Approve
```

После отката повторно проверьте, что Docker containers продолжают работать и их
volumes не изменились. Официальные основания сетевой и DPAPI-модели перечислены в
[`official-sources.md`](official-sources.md).
