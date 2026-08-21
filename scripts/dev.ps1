$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$env:CRC_ENVIRONMENT = "development"
$env:CRC_ALLOW_INSECURE_DEV_SECRETS = "true"
$env:CRC_TLS_ENABLED = "false"
uv run cyber-range-coach serve
