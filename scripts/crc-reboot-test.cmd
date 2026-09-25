<# :
@echo off
rem Run twice: now, then again after restarting the laptop.
rem Windows asks for admin rights, answer Yes.
copy /y "%~f0" "%TEMP%\crc-reboot-test.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\crc-reboot-test.ps1"
del "%TEMP%\crc-reboot-test.ps1" >nul 2>&1
pause
exit /b
#>
# Stage D5: does a firewall rule bound to the WSL adapter survive a reboot?
# Run 1 creates one test rule (TCP 47050, WSL adapter only) and remembers the
# WSL address. Run 2 after the reboot checks that WSL reaches the port on the
# re-created adapter, then deletes the rule. Result goes to the Desktop.
$ErrorActionPreference = "Continue"
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    exit
}

$port = 47050
$ruleName = "CRC reboot test (temporary)"
$state = Join-Path $env:ProgramData "crc-reboot-test.txt"
$program = (Get-Process -Id $PID).Path
$desktop = [Environment]::GetFolderPath("Desktop")

function Adapter {
    Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -like "vEthernet (WSL*" } | Select-Object -First 1
}
function WslAddress {
    return ((& wsl.exe -d Ubuntu -- hostname -I | Out-String).Trim())
}

if (-not (Test-Path -LiteralPath $state)) {
    & wsl.exe -d Ubuntu -- true
    $wsl = Adapter
    if ($null -eq $wsl) { Write-Output "WSL adapter not found. Open Ubuntu once and run again."; exit }
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Program $program `
        -Protocol TCP -LocalPort $port -InterfaceAlias $wsl.InterfaceAlias -Profile Any | Out-Null
    @("boot1 " + (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString("o"),
      "adapter1 $($wsl.InterfaceAlias) $($wsl.IPAddress)",
      "wsl1 " + (WslAddress)) | Set-Content -LiteralPath $state -Encoding ASCII
    Write-Output ""
    Write-Output "Step 1 done. Now RESTART the laptop, then run this file again."
    exit
}

$saved = Get-Content -LiteralPath $state
$before = @(Get-NetFirewallRule -PolicyStore PersistentStore | ForEach-Object { $_.Name })
$out = Join-Path $desktop ("crc-reboot-test-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".txt")
$log = @("crc-reboot-test/v2 " + (Get-Date).ToString("o")) + $saved
$log += "boot2 " + (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString("o")
& wsl.exe -d Ubuntu -- true
$wsl = Adapter
$log += "adapter2 $($wsl.InterfaceAlias) $($wsl.IPAddress)"
$log += "wsl2 " + (WslAddress)
$rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Select-Object -First 1
$log += "rule present after reboot: " + ($null -ne $rule)
$listener = $null
try {
    # A rule for this program must exist before listening, otherwise Windows may
    # show its firewall window and add a program-wide rule that spoils the test.
    New-NetFirewallRule -DisplayName "$ruleName guard" -Direction Inbound -Action Allow -Program $program `
        -Protocol TCP -LocalPort ($port + 1) -InterfaceAlias $wsl.InterfaceAlias -Profile Any | Out-Null
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($wsl.IPAddress), $port)
    $listener.Start()
    $raw = & wsl.exe -d Ubuntu -- bash -c "timeout 3 bash -c '</dev/tcp/$($wsl.IPAddress)/$port' 2>/dev/null && echo open || echo closed" | Out-String
    $log += "after reboot with rule: " + $raw.Trim()
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    $raw = & wsl.exe -d Ubuntu -- bash -c "timeout 3 bash -c '</dev/tcp/$($wsl.IPAddress)/$port' 2>/dev/null && echo open || echo closed" | Out-String
    $log += "after rule removed: " + $raw.Trim()
} catch {
    $log += "error: $($_.Exception.Message)"
} finally {
    if ($null -ne $listener) { $listener.Stop() }
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $state -ErrorAction SilentlyContinue
}
Remove-NetFirewallRule -DisplayName "$ruleName guard" -ErrorAction SilentlyContinue
$added = @(Get-NetFirewallRule -PolicyStore PersistentStore | Where-Object { $before -notcontains $_.Name })
foreach ($extra in $added) {
    $log += "cleanup removed rule added during test: $($extra.DisplayName) action=$($extra.Action) profile=$($extra.Profile)"
    $extra | Remove-NetFirewallRule
}
$log += "rules added by Windows during test: $($added.Count)"
$log += "rules left from this test: " + @(Get-NetFirewallRule -DisplayName "$ruleName*" -ErrorAction SilentlyContinue).Count
$log | Set-Content -LiteralPath $out -Encoding UTF8
$log | Out-Host
Write-Output ""
Write-Output "Done. Send the crc-reboot-test-*.txt file from your Desktop to the Mac."
