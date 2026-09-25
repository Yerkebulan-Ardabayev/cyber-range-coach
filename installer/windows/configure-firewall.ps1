[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Academy", "Relay")]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$ApplicationPath,

    [string]$WslAdapterAlias,

    [switch]$Approve
)

$ErrorActionPreference = "Stop"
$ruleGroup = "Cyber Range Coach"

if (-not $Approve) {
    throw "Изменения не внесены. Проверьте команду и повторите запуск с -Approve."
}

$privateProfiles = @(Get-NetConnectionProfile | Where-Object {
    [uint16]$_.NetworkCategory -eq 1 -and
    @("Subnet", "LocalNetwork", "Internet") -contains $_.IPv4Connectivity.ToString()
})
if ($privateProfiles.Count -eq 0) {
    throw "Активный частный сетевой профиль не найден. Публичные профили никогда не разрешаются."
}

if ($Mode -eq "Academy") {
    $name = "Cyber Range Coach UI 8443 Private LAN"
    Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
    New-NetFirewallRule `
        -DisplayName $name `
        -Group $ruleGroup `
        -Direction Inbound `
        -Action Allow `
        -Program $ApplicationPath `
        -Protocol TCP `
        -LocalPort 8443 `
        -RemoteAddress LocalSubnet `
        -Profile Private | Out-Null
    Write-Output "Создано правило академии для TCP 8443 и LocalSubnet только в частном профиле."
    exit 0
}

# Relay rule allows the WSL NAT address range, not one WSL address and not the
# WSL adapter. Checked on the owner's laptop 25.09.2026 with a reboot: a rule
# bound to the WSL adapter stopped working after the reboot, a rule for
# 172.16.0.0/12 kept working; without a rule WSL cannot reach the port. The
# WSL adapter has no network profile, so the rule uses Profile Any. That is
# safe only because the academy binds each relay to the Windows address on the
# WSL adapter (not 0.0.0.0) and accepts only the current WSL address.
$wslRange = "172.16.0.0/12"
if (-not $WslAdapterAlias) {
    $WslAdapterAlias = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -like "vEthernet (WSL*" } |
        Select-Object -First 1 -ExpandProperty InterfaceAlias
}
$wslAddress = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $WslAdapterAlias -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty IPAddress
if (-not $wslAddress) {
    throw "Виртуальный адаптер WSL не найден. Запустите Ubuntu в WSL и повторите."
}
$octets = $wslAddress.Split(".")
if ([int]$octets[0] -ne 172 -or [int]$octets[1] -lt 16 -or [int]$octets[1] -gt 31) {
    throw "Адрес WSL $wslAddress вне диапазона $wslRange. Правило relay не создано."
}
$name = "Cyber Range Coach Relay 47000-47100 from WSL $wslRange"
Get-NetFirewallRule -Group $ruleGroup -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "Cyber Range Coach Relay *" } |
    Remove-NetFirewallRule
New-NetFirewallRule `
    -DisplayName $name `
    -Group $ruleGroup `
    -Direction Inbound `
    -Action Allow `
    -Program $ApplicationPath `
    -Protocol TCP `
    -LocalPort 47000-47100 `
    -RemoteAddress $wslRange `
    -Profile Any | Out-Null
Write-Output "Создано правило relay для адресов WSL $wslRange. Адрес WSL после перезагрузки академия берёт сама."
