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

# Relay rule is bound to the WSL virtual adapter, not to the WSL address:
# WSL gets a new NAT address on every reboot, the adapter name stays. Checked on
# the owner's laptop 25.09.2026: without a rule WSL cannot reach the port, a rule
# on the Wi-Fi adapter does not help, a rule on the WSL adapter does. The WSL
# adapter has no network profile, so the rule uses Profile Any; the adapter is
# internal to this machine, and the academy still accepts relay connections only
# from the current WSL address.
if (-not $WslAdapterAlias) {
    $WslAdapterAlias = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -like "vEthernet (WSL*" } |
        Select-Object -First 1 -ExpandProperty InterfaceAlias
}
if (-not $WslAdapterAlias -or -not (Get-NetIPInterface -InterfaceAlias $WslAdapterAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
    throw "Виртуальный адаптер WSL не найден. Запустите Ubuntu в WSL и повторите."
}
$name = "Cyber Range Coach Relay 47000-47100 on WSL adapter"
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
    -InterfaceAlias $WslAdapterAlias `
    -Profile Any | Out-Null
Write-Output "Создано правило relay только на адаптере $WslAdapterAlias. Адрес WSL после перезагрузки академия берёт сама."
