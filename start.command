#!/bin/zsh
set -u
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:8899/"

if /usr/bin/curl --silent --max-time 1 "$URL" | /usr/bin/grep -q "Cyber Range Coach"; then
  /usr/bin/open "$URL"
  exit 0
fi

if /usr/sbin/lsof -nP -iTCP:8899 -sTCP:LISTEN >/dev/null 2>&1; then
  /usr/bin/osascript -e 'display alert "Cyber Range Coach" message "Порт 8899 уже занят другим процессом. Он не был остановлен." as critical'
  exit 1
fi

cd "$PROJECT_DIR" || exit 1
/usr/bin/python3 server.py >"$PROJECT_DIR/server.log" 2>&1 &
SERVER_PID=$!
for _ in {1..30}; do
  if /usr/bin/curl --silent --max-time 1 "$URL" >/dev/null; then
    /usr/bin/open "$URL"
    exit 0
  fi
  /bin/sleep 0.2
done

if /bin/kill -0 "$SERVER_PID" 2>/dev/null; then
  /bin/kill "$SERVER_PID"
fi
/usr/bin/osascript -e 'display alert "Cyber Range Coach" message "Сервер не запустился. Откройте server.log в папке проекта." as critical'
exit 1
