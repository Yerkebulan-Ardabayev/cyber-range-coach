#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

SMOKE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/cyber-range-coach-frozen.XXXXXX")"
cleanup() {
  /bin/rm -rf -- "$SMOKE_ROOT"
}
trap cleanup EXIT

export PYINSTALLER_CONFIG_DIR="$SMOKE_ROOT/pyinstaller-config"
uv run pyinstaller \
  --noconfirm \
  --clean \
  --workpath "$SMOKE_ROOT/build" \
  --distpath "$SMOKE_ROOT/dist" \
  installer/windows/CyberRangeCoach.spec

APP="$SMOKE_ROOT/dist/CyberRangeCoach/CyberRangeCoach"
DOCTOR="$SMOKE_ROOT/dist/CyberRangeCoach/CyberRangeCoachDoctor"
if [[ ! -x "$APP" || ! -x "$DOCTOR" ]]; then
  printf '%s\n' "Собранные исполняемые файлы отсутствуют или не имеют права на запуск." >&2
  exit 1
fi

SMOKE_DATA_DIR="$SMOKE_ROOT/data"
mkdir -p "$SMOKE_DATA_DIR"

"$APP" --help >/dev/null
"$DOCTOR" --help >/dev/null
if ! /usr/bin/find "$SMOKE_ROOT/dist" -path '*tzdata/zoneinfo/Asia/Almaty' -type f | /usr/bin/grep -q .; then
  printf '%s\n' "В сборке нет данных часовых поясов tzdata (нужны Windows, 25.09.2026: 422)." >&2
  exit 1
fi
CRC_DATA_DIR="$SMOKE_DATA_DIR" "$DOCTOR" >"$SMOKE_DATA_DIR/doctor.json"
uv run python -c 'import json, pathlib, sys; payload=json.loads(pathlib.Path(sys.argv[1]).read_text()); assert {"ready", "checks", "platform"} <= payload.keys()' "$SMOKE_DATA_DIR/doctor.json"
