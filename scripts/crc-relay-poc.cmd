<# :
@echo off
rem Double-click. Windows asks for admin rights once, answer Yes.
rem If Windows Firewall shows a window about PowerShell, press Cancel.
copy /y "%~f0" "%TEMP%\crc-relay-poc.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\crc-relay-poc.ps1"
del "%TEMP%\crc-relay-poc.ps1" >nul 2>&1
echo.
echo Done. Send the crc-relay-poc-*.txt file from your Desktop to the Mac.
pause
exit /b
#>
# Stage D5 PoC: can a firewall rule bound to the WSL adapter (not to the WSL
# address, which changes on every reboot) let WSL reach a Windows port?
# Test port 47050 on the WSL adapter address only, never on the LAN.
# Everything this script creates is removed at the end, including any rule
# Windows adds if a firewall window appears; the log shows what was removed.
$ErrorActionPreference = "Continue"
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    exit
}

$out = Join-Path ([Environment]::GetFolderPath("Desktop")) ("crc-relay-poc-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".txt")
$log = @("crc-relay-poc/v2 " + (Get-Date).ToString("o"))
$port = 47050
$ruleName = "CRC PoC relay test (temporary)"
$before = @(Get-NetFirewallRule -PolicyStore PersistentStore | ForEach-Object { $_.Name })

function Probe([string]$Address) {
    $raw = & wsl.exe -d Ubuntu -- bash -c "timeout 3 bash -c '</dev/tcp/$Address/$port' 2>/dev/null && echo open || echo closed" | Out-String
    return $raw.Trim()
}

$wsl = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -like "vEthernet (WSL*" } | Select-Object -First 1
if ($null -eq $wsl) {
    $log += "WSL adapter not found"
} else {
    $alias = $wsl.InterfaceAlias
    $address = $wsl.IPAddress
    $log += "wsl adapter: $alias $address/$($wsl.PrefixLength)"
    $profileInfo = Get-NetConnectionProfile -InterfaceAlias $alias -ErrorAction SilentlyContinue
    $log += "wsl adapter profile: " + $(if ($profileInfo) { $profileInfo.NetworkCategory } else { "none" })
    & wsl.exe -d Ubuntu -- true
    $log += "wsl ubuntu address: " + ((& wsl.exe -d Ubuntu -- hostname -I | Out-String).Trim())

    $listener = $null
    $program = (Get-Process -Id $PID).Path
    try {
        # A rule for this program must exist before listening, otherwise
        # Windows shows its firewall window and may add a program-wide rule
        # that spoils the test. This guard rule is for another port.
        New-NetFirewallRule -DisplayName "$ruleName guard" -Direction Inbound -Action Allow -Program $program `
            -Protocol TCP -LocalPort ($port + 1) -InterfaceAlias $alias -Profile Any | Out-Null
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($address), $port)
        $listener.Start()
        $log += "listener: $address`:$port"
        $log += "A no rule for this port: " + (Probe $address)
        $wifi = (Get-NetConnectionProfile | Select-Object -First 1).InterfaceAlias
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Program $program `
            -Protocol TCP -LocalPort $port -InterfaceAlias $wifi -Profile Any | Out-Null
        $log += "B rule on other adapter ($wifi): " + (Probe $address)
        Remove-NetFirewallRule -DisplayName $ruleName
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Program $program `
            -Protocol TCP -LocalPort $port -InterfaceAlias $alias -Profile Any | Out-Null
        $log += "C rule on WSL adapter: " + (Probe $address)
        Remove-NetFirewallRule -DisplayName $ruleName
        $log += "D rule removed again: " + (Probe $address)
        $auto = @(Get-NetFirewallRule -PolicyStore PersistentStore | Where-Object { $before -notcontains $_.Name -and $_.DisplayName -notlike "$ruleName*" })
        $log += "rules added by Windows during test: $($auto.Count)"
    } catch {
        $log += "error: $($_.Exception.Message)"
    } finally {
        if ($null -ne $listener) { $listener.Stop() }
    }
}

$added = @(Get-NetFirewallRule -PolicyStore PersistentStore | Where-Object { $before -notcontains $_.Name })
foreach ($rule in $added) {
    $log += "cleanup removed rule: $($rule.DisplayName) action=$($rule.Action) profile=$($rule.Profile)"
    $rule | Remove-NetFirewallRule
}
$left = @(Get-NetFirewallRule -PolicyStore PersistentStore | Where-Object { $before -notcontains $_.Name })
$log += "rules left from this test: $($left.Count)"

$log | Set-Content -LiteralPath $out -Encoding UTF8
$log | Out-Host
