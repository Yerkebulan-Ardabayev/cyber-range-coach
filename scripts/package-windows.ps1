[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$PrepareOcr
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($PrepareOcr) {
    & "$PSScriptRoot\prepare-ocr.ps1" -ApproveDownload
}
if (-not (Test-Path -LiteralPath "vendor\tesseract\tesseract.exe" -PathType Leaf)) {
    throw "Проверка встроенного OCR не пройдена: отсутствует vendor\tesseract\tesseract.exe. Перед упаковкой добавьте проверенную и закреплённую версию Tesseract для Windows."
}
if (-not (Get-Command iscc.exe -ErrorAction SilentlyContinue)) {
    throw "На Windows build host требуется компилятор Inno Setup."
}

if (-not $SkipTests) {
    uv run ruff check backend
    uv run mypy backend/src
    uv run pytest
    uv run python scripts\secret_scan.py
    Push-Location frontend
    try {
        npm ci
        npm run lint
        npm run typecheck
        npm run test
        npm run build
    }
    finally {
        Pop-Location
    }
}

uv run pyinstaller --noconfirm --clean installer\windows\CyberRangeCoach.spec
iscc.exe installer\windows\CyberRangeCoach.iss
$Artifact = Resolve-Path "dist\installer\CyberRangeCoach-Setup.exe"
$Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact
"$($Hash.Hash.ToLowerInvariant())  $($Artifact.Path)" | Set-Content -Encoding ascii "dist\installer\CyberRangeCoach-Setup.exe.sha256"
Write-Output "Установщик Windows: $($Artifact.Path)"
Write-Output "SHA256: $($Hash.Hash.ToLowerInvariant())"
