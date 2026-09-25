<# :
@echo off
rem Double-click. Windows asks for admin rights once, answer Yes.
copy /y "%~f0" "%TEMP%\crc-fix.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\crc-fix.ps1"
del "%TEMP%\crc-fix.ps1" >nul 2>&1
echo.
echo Done. Send the crc-fix-*.txt file from your Desktop to the Mac.
pause
exit /b
#>
# 1) Disable the range rule that is open in the Public network profile.
#    The home access rule "CyberLab LAN only (Private, Mac)" is not touched.
# 2) Install nmap, tcpdump and jq in WSL Ubuntu (as root, no password needed).
$ErrorActionPreference = "Continue"
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    exit
}

$out = Join-Path ([Environment]::GetFolderPath("Desktop")) ("crc-fix-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".txt")
$log = @("crc-fix/v1 " + (Get-Date).ToString("o"))

$public = "CyberLab LAN only"
if (Get-NetFirewallRule -DisplayName $public -ErrorAction SilentlyContinue) {
    Disable-NetFirewallRule -DisplayName $public
}
foreach ($name in @($public, "CyberLab LAN only (Private, Mac)")) {
    $rule = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $rule) { $log += "rule '$name': not found" }
    else { $log += "rule '$name': enabled=$($rule.Enabled) profile=$($rule.Profile)" }
}

Write-Output "Installing nmap, tcpdump, jq in Ubuntu, 1-3 minutes..."
& wsl.exe -d Ubuntu -u root -- bash -c "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq nmap tcpdump jq"
$log += "apt exit=$LASTEXITCODE"
$tools = & wsl.exe -d Ubuntu -u root -- bash -c "for t in nmap tcpdump jq; do printf '%s ' `$t; command -v `$t || echo MISSING; done" | Out-String
$log += $tools.Trim()

$log | Set-Content -LiteralPath $out -Encoding UTF8
$log | Out-Host
