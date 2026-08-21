[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Academy", "Relay")]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$ApplicationPath,

    [string]$LinuxVmIp,

    [switch]$Approve
)

$ErrorActionPreference = "Stop"
$ruleGroup = "Cyber Range Coach"

if (-not $Approve) {
    throw "Изменения не внесены. Проверьте команду и повторите запуск с -Approve."
}

$privateProfiles = @(Get-NetConnectionProfile | Where-Object {
    $_.NetworkCategory -eq "Private" -and
    @("Subnet", "LocalNetwork", "Internet") -contains $_.IPv4Connectivity
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

$parsedIp = $null
if (-not [System.Net.IPAddress]::TryParse($LinuxVmIp, [ref]$parsedIp) -or $parsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "Для режима relay требуется точный IPv4-адрес Linux VM."
}
$name = "Cyber Range Coach Relay 47000-47100 from $LinuxVmIp"
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
    -RemoteAddress $LinuxVmIp `
    -Profile Private | Out-Null
Write-Output "Создано правило relay только для частного профиля и точного источника $LinuxVmIp."
