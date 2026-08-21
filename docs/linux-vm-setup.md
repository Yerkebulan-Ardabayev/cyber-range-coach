# Подключение Linux VM

Docker внутри Linux VM для первой версии не нужен. VM является атакующей учебной
машиной, а targets продолжают работать в Docker Desktop на Windows.

## Две роли

После сохранения IP VM и usernames академия создаёт две разные пары Ed25519 keys:

- `student`: интерактивный browser terminal без административных прав;
- `range-runner`: forced-command учётная запись без общего shell, PTY, agent
  forwarding и port forwarding.

Приватные keys в Windows-релизе защищены DPAPI. В интерфейсе показываются только
public keys.

## Явная настройка VM

В разделе `Система` скачайте в одну папку VM:

- `bootstrap-linux.sh`;
- `crc-range-check`.

Сначала прочитайте оба файла. Затем выполните показанную интерфейсом команду
`sudo bash bootstrap-linux.sh ...`. Это единственный этап, где владелец вручную
использует sudo для настройки учебных ролей. Скрипт:

1. Отказывается изменять существующего пользователя, если тот не помечен как
   созданный Cyber Range Coach.
2. Создаёт или обновляет только две указанные роли.
3. Блокирует password login этих ролей и устанавливает отдельные authorized keys.
4. Удаляет `student` из групп `sudo`, `wheel`, `admin`, `docker`, `lxd`.
5. От root проверяет полный `sudo -l -U student` и прекращает настройку при любой
   записи sudo policy. Затем от имени `student` отдельно проверяет
   `sudo -n -l` и `sudo -n true`, чтобы поймать restricted `NOPASSWD` rule.
6. Фактически проверяет чтение и запись известных `/var/run/docker.sock` и
   `/run/user/<uid>/docker.sock`; доступ делает setup неуспешным.
7. Закрепляет за runner `/usr/local/lib/cyber-range-coach/crc-range-check`.
8. Записывает проверенный Windows relay host в root-owned configuration.

Удаление групп само по себе не доказывает безопасность: sudoers include, ACL или
world-writable socket могут дать доступ вне групп. Bootstrap проверяет полный
sudo policy с правами root. Backend перед каждым lab повторяет non-interactive
sudo и Docker-socket probes, чтобы обнаружить изменение после bootstrap.

Если OpenSSH server отсутствует, bootstrap его не устанавливает. Установку пакета
своего дистрибутива надо отдельно подтвердить, затем повторить preflight.

## Разрешённые probes range-runner

`range-runner` принимает только protocol `crc-range-check/v1` и следующие формы:

- `tools`: наличие учебных CLI tools;
- `relay <port>`: TCP connect к закреплённому Windows host и порту 47000..47100;
- `nmap <port>`: `nmap -sV -Pn` одного порта на закреплённом host;
- `http <port> <scheme> <base64url-path>`: HTTP GET через relay с проверенным
  port, scheme и path.

HTTP probe возвращает JSON только с method, подтверждённым path, принудительным
request protocol HTTP/1.1, наличием Host, response protocol, numeric status и
наличием хотя бы одного response header. Body и значения headers не возвращаются.
Любой другой текст отклоняется и не исполняется как shell command.

Здесь `-Pn` пропускает обычный IP-level host discovery, не только ICMP. На
локальном Ethernet Nmap всё ещё может использовать ARP или Neighbor Discovery.
Probe сканирует один заранее выбранный relay port. Источник указан в
[`official-sources.md`](official-sources.md).

## Host fingerprint

Первый SSH probe аутентифицирует generated key, но не доверяет host key
автоматически. Внутри VM выполните:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Сравните fingerprint символ в символ с Windows UI и только затем нажмите
`Подтвердить fingerprint`. При изменении host key профиль снова становится
неподтверждённым до ручной сверки.

## Проверка маршрута

После настройки нажмите `Проверить range-runner`. Успешный JSON должен содержать
`crc-range-check/v1`, а каждое поле обязательного инструмента должно быть `true`.
Одного protocol marker недостаточно. Lab с Docker target дополнительно запускает
временный relay и требует структурированное наблюдение именно из VM. Простой TCP
connect с Windows не заменяет этот test.

Реальная проверка Linux VM ещё не выполнена в текущей macOS-сессии. До неё нельзя
утверждать, что конкретная VM, sudoers, ACL, SSH server и network route безопасны.
