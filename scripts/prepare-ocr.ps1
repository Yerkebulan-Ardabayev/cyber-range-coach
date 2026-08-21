[CmdletBinding()]
param(
    [switch]$ApproveDownload,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
if (-not $ApproveDownload) {
    throw "Загрузка не выполнялась. Проверьте закреплённые URL и хэши, затем повторите запуск с -ApproveDownload."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Destination = Join-Path $ProjectRoot "vendor\tesseract"
$TesseractUrl = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe"
$TesseractSha256 = "bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4"
$TessdataCommit = "87416418657359cb625c412a48b6e1d6d41c29bd"
$Languages = @{
    "eng.traineddata" = @{
        Url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/$TessdataCommit/eng.traineddata"
        Sha256 = "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
    }
    "rus.traineddata" = @{
        Url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/$TessdataCommit/rus.traineddata"
        Sha256 = "e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225"
    }
}

if ((Test-Path -LiteralPath (Join-Path $Destination "tesseract.exe")) -and -not $Force) {
    throw "OCR runtime уже существует. Проверьте его или повторите запуск с -Force, чтобы заменить только vendor\tesseract."
}
if (-not (Get-Command 7z.exe -ErrorAction SilentlyContinue)) {
    throw "Для распаковки закреплённого официального release asset требуется команда 7z.exe из 7-Zip."
}

$TaskTemp = Join-Path ([IO.Path]::GetTempPath()) ("crc-ocr-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TaskTemp | Out-Null
try {
    $Installer = Join-Path $TaskTemp "tesseract-setup.exe"
    $Extracted = Join-Path $TaskTemp "extracted"
    Invoke-WebRequest -Uri $TesseractUrl -OutFile $Installer
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash.ToLowerInvariant()
    if ($Actual -ne $TesseractSha256) {
        throw "SHA-256 Tesseract не совпадает. Ожидался $TesseractSha256, получен $Actual."
    }
    New-Item -ItemType Directory -Path $Extracted | Out-Null
    & 7z.exe x $Installer "-o$Extracted" -y | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $Extracted "tesseract.exe"))) {
        throw "В закреплённом архиве Tesseract не найден tesseract.exe по ожидаемому пути."
    }
    if ($Force -and (Test-Path -LiteralPath $Destination)) {
        Get-ChildItem -LiteralPath $Destination -Force |
            Where-Object { $_.Name -ne "README.md" } |
            Remove-Item -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Extracted -Force |
        Where-Object { $_.Name -ne '$PLUGINSDIR' } |
        Copy-Item -Destination $Destination -Recurse -Force

    $Tessdata = Join-Path $Destination "tessdata"
    New-Item -ItemType Directory -Path $Tessdata -Force | Out-Null
    foreach ($Language in $Languages.GetEnumerator()) {
        $Output = Join-Path $Tessdata $Language.Key
        Invoke-WebRequest -Uri $Language.Value.Url -OutFile $Output
        $LanguageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Output).Hash.ToLowerInvariant()
        if ($LanguageHash -ne $Language.Value.Sha256) {
            throw "SHA-256 файла $($Language.Key) не совпадает."
        }
    }
    & (Join-Path $Destination "tesseract.exe") --version
}
finally {
    if (Test-Path -LiteralPath $TaskTemp) {
        Remove-Item -LiteralPath $TaskTemp -Recurse -Force
    }
}
