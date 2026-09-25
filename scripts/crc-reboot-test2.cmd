<# :
@echo off
rem Run twice: now, then again after restarting the laptop.
rem Windows asks for admin rights, answer Yes.
copy /y "%~f0" "%TEMP%\crc-reboot-test2.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\crc-reboot-test2.ps1"
del "%TEMP%\crc-reboot-test2.ps1" >nul 2>&1
pause
exit /b
#>
# Stage D5, second try. The rule bound to the WSL adapter did not work after a
# reboot. Run 1 creates two test rules: by WSL adapter (port 47050) and by WSL
# address range 172.16.0.0/12 (port 47052). Run 2 after the reboot tests both,
# then a fresh adapter rule (port 47054), and removes everything it created.
$ErrorActionPreference = "Continue"
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    exit
}

$prefix = "CRC reboot test2"
$state = Join-Path $env:ProgramData "crc-reboot-test2.txt"
$program = (Get-Process -Id $PID).Path
$desktop = [Environment]::GetFolderPath("Desktop")

function Adapter {
    Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -like "vEthernet (WSL*" } | Select-Object -First 1
}
function WslAddress { return ((& wsl.exe -d Ubuntu -- hostname -I | Out-String).Trim()) }
function Probe([string]$Address, [int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($Address), $Port)
    try {
        $listener.Start()
        $raw = & wsl.exe -d Ubuntu -- bash -c "timeout 3 bash -c '</dev/tcp/$Address/$Port' 2>/dev/null && echo open || echo closed" | Out-String
        return $raw.Trim()
    } finally { $listener.Stop() }
}

if (-not (Test-Path -LiteralPath $state)) {
    & wsl.exe -d Ubuntu -- true
    $wsl = Adapter
    if ($null -eq $wsl) { Write-Output "WSL adapter not found. Open Ubuntu once and run again."; exit }
    Get-NetFirewallRule -DisplayName "$prefix*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName "$prefix adapter" -Direction Inbound -Action Allow -Program $program `
        -Protocol TCP -LocalPort 47050 -InterfaceAlias $wsl.InterfaceAlias -Profile Any | Out-Null
    New-NetFirewallRule -DisplayName "$prefix range" -Direction Inbound -Action Allow -Program $program `
        -Protocol TCP -LocalPort 47052 -RemoteAddress 172.16.0.0/12 -Profile Any | Out-Null
    $before1 = Probe $wsl.IPAddress 47050
    $before2 = Probe $wsl.IPAddress 47052
    @("boot1 " + (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString("o"),
      "adapter1 $($wsl.InterfaceAlias) $($wsl.IPAddress) wsl1 " + (WslAddress),
      "before reboot adapter rule: $before1",
      "before reboot range rule: $before2") | Set-Content -LiteralPath $state -Encoding ASCII
    Get-Content -LiteralPath $state | Out-Host
    Write-Output ""
    Write-Output "Step 1 done. Now RESTART the laptop, then run this file again."
    exit
}

$saved = Get-Content -LiteralPath $state
$before = @(Get-NetFirewallRule -PolicyStore PersistentStore | ForEach-Object { $_.Name })
$out = Join-Path $desktop ("crc-reboot-test2-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".txt")
$log = @("crc-reboot-test2/v1 " + (Get-Date).ToString("o")) + $saved
$log += "boot2 " + (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString("o")
& wsl.exe -d Ubuntu -- true
$wsl = Adapter
$log += "adapter2 $($wsl.InterfaceAlias) $($wsl.IPAddress) wsl2 " + (WslAddress)
try {
    $log += "after reboot adapter rule: " + (Probe $wsl.IPAddress 47050)
    $log += "after reboot range rule: " + (Probe $wsl.IPAddress 47052)
    New-NetFirewallRule -DisplayName "$prefix fresh adapter" -Direction Inbound -Action Allow -Program $program `
        -Protocol TCP -LocalPort 47054 -InterfaceAlias $wsl.InterfaceAlias -Profile Any | Out-Null
    $log += "after reboot fresh adapter rule: " + (Probe $wsl.IPAddress 47054)
    $log += "no rule at all: " + (Probe $wsl.IPAddress 47056)
} catch {
    $log += "error: $($_.Exception.Message)"
} finally {
    Get-NetFirewallRule -DisplayName "$prefix*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Remove-Item -LiteralPath $state -ErrorAction SilentlyContinue
}
$added = @(Get-NetFirewallRule -PolicyStore PersistentStore | Where-Object { $before -notcontains $_.Name })
foreach ($extra in $added) {
    $log += "cleanup removed rule added during test: $($extra.DisplayName) action=$($extra.Action) profile=$($extra.Profile)"
    $extra | Remove-NetFirewallRule
}
$log += "rules added by Windows during test: $($added.Count)"
$log += "rules left from this test: " + @(Get-NetFirewallRule -DisplayName "$prefix*" -ErrorAction SilentlyContinue).Count
$log | Set-Content -LiteralPath $out -Encoding UTF8
$log | Out-Host
Write-Output ""
Write-Output "Done. Send the crc-reboot-test2-*.txt file from your Desktop to the Mac."
