#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CRC_ENVIRONMENT=development
export CRC_ALLOW_INSECURE_DEV_SECRETS=true
export CRC_TLS_ENABLED=false
exec uv run cyber-range-coach serve
