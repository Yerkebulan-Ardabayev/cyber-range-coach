<# :
@echo off
rem Double-click. Windows asks for admin rights once, answer Yes.
copy /y "%~f0" "%TEMP%\crc-lan-rule.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\crc-lan-rule.ps1"
del "%TEMP%\crc-lan-rule.ps1" >nul 2>&1
echo.
echo Done. Send the crc-lan-rule-*.txt file from your Desktop to the Mac.
pause
exit /b
#>
# Rule "CyberLab LAN only (Private, Mac)": allow any device of the home subnet
# (LocalSubnet) instead of the single Mac address, Private profile only.
$ErrorActionPreference = "Continue"
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    exit
}

$out = Join-Path ([Environment]::GetFolderPath("Desktop")) ("crc-lan-rule-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".txt")
$log = @("crc-lan-rule/v1 " + (Get-Date).ToString("o"))
$name = "CyberLab LAN only (Private, Mac)"

function Describe([string]$Label) {
    $rule = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $rule) { return "$Label rule not found" }
    $address = ($rule | Get-NetFirewallAddressFilter).RemoteAddress -join ","
    $ports = ($rule | Get-NetFirewallPortFilter).LocalPort -join ","
    return "$Label enabled=$($rule.Enabled) profile=$($rule.Profile) remote=$address ports=$ports"
}

$log += Describe "before:"
if (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -DisplayName $name -RemoteAddress LocalSubnet -Profile Private
}
$log += Describe "after:"

$log | Set-Content -LiteralPath $out -Encoding UTF8
$log | Out-Host
