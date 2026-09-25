#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

uv run ruff check backend scripts/secret_scan.py tools/capture_linux_outputs.py tools/live_mission_seed.py tools/validate_ladder.py tools/validate_simple_theory.py tools/validate_command_techniques.py range_discovery.py tools/test_range_discovery.py
uv run mypy backend/src
uv run pytest
uv run python tools/validate_command_techniques.py
uv run python tools/validate_missions.py
uv run python tools/validate_simple_theory.py
uv run python scripts/secret_scan.py
/usr/bin/python3 tools/test_range_discovery.py
/usr/bin/python3 tools/test_learning_flow.py
pwsh -NoProfile -File tools/check_powershell.ps1 scripts/windows-poc-probe.ps1 scripts/windows-lan-rule-localsubnet.ps1
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
