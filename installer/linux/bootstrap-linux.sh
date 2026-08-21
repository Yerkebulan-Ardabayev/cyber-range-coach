#!/usr/bin/env bash
set -euo pipefail

student_user="student"
runner_user="range-runner"
student_key=""
runner_key=""
relay_host=""

usage() {
  printf '%s\n' "Использование: sudo bash bootstrap-linux.sh --student-key КЛЮЧ --runner-key КЛЮЧ --relay-host IPV4_WINDOWS [--student-user ИМЯ] [--runner-user ИМЯ]"
}

while (( $# > 0 )); do
  case "$1" in
    --student-key) student_key="${2:-}"; shift 2 ;;
    --runner-key) runner_key="${2:-}"; shift 2 ;;
    --relay-host) relay_host="${2:-}"; shift 2 ;;
    --student-user) student_user="${2:-}"; shift 2 ;;
    --runner-user) runner_user="${2:-}"; shift 2 ;;
    *) usage; exit 64 ;;
  esac
done

if (( EUID != 0 )); then
  printf '%s\n' "Проверьте сценарий, затем запустите его через sudo." >&2
  exit 77
fi
if [[ ! "$student_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || [[ ! "$runner_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
  printf '%s\n' "Недопустимое имя пользователя Linux." >&2
  exit 65
fi
if [[ ! "$student_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+ ]] || [[ ! "$runner_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+ ]]; then
  printf '%s\n' "Оба открытых ключа должны быть ключами OpenSSH Ed25519." >&2
  exit 65
fi
if [[ ! "$relay_host" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  printf '%s\n' "Адрес relay должен быть IPv4-адресом Windows, показанным академией." >&2
  exit 65
fi
if [[ ! -f ./crc-range-check ]]; then
  printf '%s\n' "Поместите crc-range-check рядом с bootstrap-linux.sh." >&2
  exit 66
fi

ensure_crc_user() {
  local user_name="$1"
  local shell_path="$2"
  if id "$user_name" >/dev/null 2>&1; then
    current_comment="$(getent passwd "$user_name" | cut -d: -f5)"
    if [[ "$current_comment" != "Cyber Range Coach" ]]; then
      printf '%s\n' "Существующий пользователь $user_name не принадлежит Cyber Range Coach, изменение запрещено." >&2
      exit 73
    fi
  else
    useradd --create-home --comment "Cyber Range Coach" --shell "$shell_path" "$user_name"
  fi
  passwd --lock "$user_name" >/dev/null 2>&1 || true
}

write_authorized_key() {
  local user_name="$1"
  local key_line="$2"
  local home_dir
  home_dir="$(getent passwd "$user_name" | cut -d: -f6)"
  install -d -o "$user_name" -g "$user_name" -m 0700 "$home_dir/.ssh"
  printf '%s\n' "$key_line" > "$home_dir/.ssh/authorized_keys"
  chown "$user_name:$user_name" "$home_dir/.ssh/authorized_keys"
  chmod 0600 "$home_dir/.ssh/authorized_keys"
}

ensure_crc_user "$student_user" /bin/bash
ensure_crc_user "$runner_user" /bin/bash

for risky_group in sudo wheel admin docker lxd; do
  if getent group "$risky_group" >/dev/null 2>&1 && id -nG "$student_user" | tr ' ' '\n' | grep -Fxq "$risky_group"; then
    gpasswd --delete "$student_user" "$risky_group" >/dev/null
  fi
done

write_authorized_key "$student_user" "$student_key"
install -d -o root -g root -m 0755 /usr/local/lib/cyber-range-coach
install -o root -g root -m 0755 ./crc-range-check /usr/local/lib/cyber-range-coach/crc-range-check
install -d -o root -g root -m 0755 /etc/cyber-range-coach
printf '%s\n' "$relay_host" > /etc/cyber-range-coach/relay-host
chown root:root /etc/cyber-range-coach/relay-host
chmod 0644 /etc/cyber-range-coach/relay-host

runner_options='restrict,command="/usr/local/lib/cyber-range-coach/crc-range-check"'
write_authorized_key "$runner_user" "$runner_options $runner_key"

run_as_student() {
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$student_user" -- "$@"
  else
    su -s /bin/sh "$student_user" -c "$(printf '%q ' "$@")"
  fi
}

if command -v sudo >/dev/null 2>&1; then
  if sudo -n -l -U "$student_user" >/dev/null 2>&1; then
    printf '%s\n' "Небезопасная настройка остановлена: для student найдено правило sudo." >&2
    exit 78
  fi
  if run_as_student sudo -n -l >/dev/null 2>&1 || run_as_student sudo -n true >/dev/null 2>&1; then
    printf '%s\n' "Небезопасная настройка остановлена: student может использовать sudo без интерактивного ввода." >&2
    exit 78
  fi
fi
if run_as_student sh -c '
  uid=$(id -u)
  for socket in /var/run/docker.sock /run/user/$uid/docker.sock; do
    if [ -e "$socket" ] && { [ -r "$socket" ] || [ -w "$socket" ]; }; then exit 0; fi
  done
  exit 1
'; then
  printf '%s\n' "Небезопасная настройка остановлена: student имеет доступ к Docker socket." >&2
  exit 78
fi

printf '%s\n' "Роли Cyber Range Coach в Linux настроены."
printf 'student=%s runner=%s relay_host=%s\n' "$student_user" "$runner_user" "$relay_host"
