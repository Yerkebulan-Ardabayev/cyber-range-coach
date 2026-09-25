[CmdletBinding()]
param(
    [string]$RuleName = "CyberLab LAN only (Private, Mac)",
    [switch]$Approve
)

# Spec 11.3 Zh / 11.7: the range rule must not depend on the Mac's DHCP address.
# Replaces only RemoteAddress of the existing rule with LocalSubnet and keeps the
# rule in the Private profile. Run from an elevated PowerShell by the owner.

$ErrorActionPreference = "Stop"

$rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $rule) {
    throw "Rule '$RuleName' not found. Nothing changed."
}
$before = ($rule | Get-NetFirewallAddressFilter).RemoteAddress
$ports = ($rule | Get-NetFirewallPortFilter).LocalPort
Write-Output "Now: RemoteAddress=$($before -join ',') LocalPort=$($ports -join ',') Profile=$($rule.Profile)"

if (-not $Approve) {
    Write-Output "Dry run. Repeat with -Approve to set RemoteAddress=LocalSubnet and Profile=Private."
    exit 0
}

Set-NetFirewallRule -DisplayName $RuleName -RemoteAddress LocalSubnet -Profile Private
$after = Get-NetFirewallRule -DisplayName $RuleName | Select-Object -First 1
$address = ($after | Get-NetFirewallAddressFilter).RemoteAddress
if (@($address) -notcontains "LocalSubnet" -or $after.Profile.ToString() -ne "Private") {
    throw "Rule was not updated as expected: RemoteAddress=$($address -join ','), Profile=$($after.Profile)"
}
Write-Output "Done: RemoteAddress=LocalSubnet Profile=Private LocalPort=$($ports -join ',')"
