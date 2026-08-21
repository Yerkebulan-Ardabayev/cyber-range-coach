[CmdletBinding()]
param([switch]$Approve)

$ErrorActionPreference = "Stop"
if (-not $Approve) {
    throw "Изменения не внесены. Проверьте команду и повторите запуск с -Approve."
}
Get-NetFirewallRule -Group "Cyber Range Coach" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
Write-Output "Удалены только правила Firewall из группы Cyber Range Coach."
