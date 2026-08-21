#!/usr/bin/env bash
set -euo pipefail

approve_install=false
forwarded=()

while (( $# > 0 )); do
  case "$1" in
    --approve-install) approve_install=true; shift ;;
    *) forwarded+=("$1"); shift ;;
  esac
done

if (( EUID != 0 )); then
  printf '%s\n' "Для установки OpenSSH и создания учебных пользователей нужен sudo-пароль вашего обычного пользователя Ubuntu." >&2
  printf '%s\n' "Cyber Range Coach не запрашивает и не сохраняет этот пароль. Повторите показанную мастером команду через sudo." >&2
  exit 77
fi

if [[ ! -r /etc/os-release ]]; then
  printf '%s\n' "Не удалось определить дистрибутив WSL." >&2
  exit 65
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  printf '%s\n' "Этот мастер предназначен только для Ubuntu в WSL." >&2
  exit 65
fi

declare -A package_for=(
  [sshd]="openssh-server"
  [curl]="curl"
  [nmap]="nmap"
  [nc]="netcat-openbsd"
  [ip]="iproute2"
  [less]="less"
)
packages=()
for command_name in "${!package_for[@]}"; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    packages+=("${package_for[$command_name]}")
  fi
done
if (( ${#packages[@]} > 0 )); then
  if [[ "$approve_install" != true ]]; then
    printf 'Нужна явная установка пакетов Ubuntu: %s\n' "${packages[*]}" >&2
    printf '%s\n' "Повторите команду с --approve-install после проверки списка." >&2
    exit 79
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install --yes --no-install-recommends "${packages[@]}"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"
bash ./bootstrap-linux.sh "${forwarded[@]}"

install -d -o root -g root -m 0755 /run/sshd
/usr/sbin/sshd -t
if command -v systemctl >/dev/null 2>&1 && [[ "$(ps -p 1 -o comm= | tr -d ' ')" == "systemd" ]]; then
  systemctl enable --now ssh
else
  service ssh restart
fi

if ! ss -ltn | awk '$4 ~ /:22$/ { found=1 } END { exit found ? 0 : 1 }'; then
  printf '%s\n' "OpenSSH установлен, но порт 22 внутри WSL не слушается." >&2
  exit 70
fi
printf '%s\n' "WSL Ubuntu готова: OpenSSH слушает TCP 22, роли student и range-runner настроены."
