#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

uv run ruff check backend scripts/secret_scan.py
uv run mypy backend/src
uv run pytest
uv run python scripts/secret_scan.py
/bin/bash -n \
  installer/linux/bootstrap-linux.sh \
  installer/linux/bootstrap-wsl-ubuntu.sh \
  installer/linux/crc-range-check \
  scripts/dev.sh \
  scripts/frozen-smoke.sh \
  scripts/quality.sh

cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
cd ..
/bin/bash scripts/frozen-smoke.sh
cd frontend
npm run test:e2e
