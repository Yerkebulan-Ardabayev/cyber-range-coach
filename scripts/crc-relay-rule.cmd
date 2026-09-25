<# :
@echo off
rem Double-click AFTER installing CyberRangeCoach-Setup.exe. Answer Yes to admin rights.
copy /y "%~f0" "%TEMP%\crc-relay-rule.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\crc-relay-rule.ps1"
del "%TEMP%\crc-relay-rule.ps1" >nul 2>&1
pause
exit /b
#>
# Creates the one-time relay firewall rule with the installed academy script
# (range 172.16.0.0/12, academy program only) and writes the result.
$ErrorActionPreference = "Continue"
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    exit
}
$app = Join-Path $env:ProgramFiles "Cyber Range Coach"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) ("crc-relay-rule-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".txt")
$log = @("crc-relay-rule/v1 " + (Get-Date).ToString("o"))
& wsl.exe -d Ubuntu -- true
try {
    $log += (& (Join-Path $app "tools\configure-firewall.ps1") -Mode Relay -ApplicationPath (Join-Path $app "CyberRangeCoach.exe") -Approve 2>&1 | Out-String).Trim()
} catch { $log += "error: $($_.Exception.Message)" }
foreach ($rule in @(Get-NetFirewallRule -Group "Cyber Range Coach" -ErrorAction SilentlyContinue)) {
    $address = ($rule | Get-NetFirewallAddressFilter).RemoteAddress -join ","
    $ports = ($rule | Get-NetFirewallPortFilter).LocalPort -join ","
    $log += "rule: $($rule.DisplayName) enabled=$($rule.Enabled) profile=$($rule.Profile) remote=$address ports=$ports"
}
$log += "installed version: " + (Get-Item (Join-Path $app "CyberRangeCoach.exe") -ErrorAction SilentlyContinue).VersionInfo.FileVersion
$log | Set-Content -LiteralPath $out -Encoding UTF8
$log | Out-Host
Write-Output ""
Write-Output "Done. Send the crc-relay-rule-*.txt file from your Desktop to the Mac."
