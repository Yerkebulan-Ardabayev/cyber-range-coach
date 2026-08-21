[CmdletBinding()]
param(
    [string]$DoctorPath = "$env:ProgramFiles\Cyber Range Coach\CyberRangeCoachDoctor.exe",
    [string]$ApplicationPath = "$env:ProgramFiles\Cyber Range Coach\CyberRangeCoach.exe",
    [string]$DataDir = "$env:LOCALAPPDATA\CyberRangeCoach",
    [string]$WslDistribution = "Ubuntu",
    [switch]$ConfigureFirewall,
    [switch]$Approve
)

$ErrorActionPreference = "Stop"
$privateProfiles = @(Get-NetConnectionProfile | Where-Object {
    [uint16]$_.NetworkCategory -eq 1 -and
    @("Subnet", "LocalNetwork", "Internet") -contains $_.IPv4Connectivity.ToString()
})
if ($privateProfiles.Count -eq 0) {
    throw "No active Private IPv4 profile was found."
}

$caPath = Join-Path $DataDir "certificates\cyber-range-coach-ca.crt"
if (-not (Test-Path -LiteralPath $caPath -PathType Leaf)) {
    throw "The app-owned root CA file is missing: $caPath"
}
$ca = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($caPath)
$trustedCa = Get-Item -LiteralPath "Cert:\CurrentUser\Root\$($ca.Thumbprint)" `
    -ErrorAction SilentlyContinue
if ($null -eq $trustedCa) {
    throw "The exact cyber-range-coach-ca.crt certificate is not trusted in CurrentUser\Root."
}

if ($ConfigureFirewall) {
    if (-not $Approve) {
        throw "Firewall mutation requires both -ConfigureFirewall and -Approve."
    }
    & "$PSScriptRoot\..\installer\windows\configure-firewall.ps1" `
        -Mode Academy -ApplicationPath $ApplicationPath -Approve
}
$rule = Get-NetFirewallRule -DisplayName "Cyber Range Coach UI 8443 Private LAN" `
    -PolicyStore ActiveStore -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $rule) {
    throw "The Cyber Range Coach TCP 8443 firewall rule is missing."
}
$portFilter = $rule | Get-NetFirewallPortFilter
$addressFilter = $rule | Get-NetFirewallAddressFilter
$firewallReady = `
    $rule.Enabled.ToString() -eq "True" -and `
    $rule.Direction.ToString() -eq "Inbound" -and `
    $rule.Action.ToString() -eq "Allow" -and `
    [uint32]$rule.Profile -eq 2 -and `
    (($portFilter.Protocol.ToString() -eq "TCP") -or ([uint16]$portFilter.Protocol -eq 6)) -and `
    (@($portFilter.LocalPort) -contains "8443") -and `
    (@($addressFilter.RemoteAddress) -contains "LocalSubnet")
if (-not $firewallReady) {
    throw "The firewall rule is not limited to TCP 8443, Private, and LocalSubnet."
}

if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 22 -InformationLevel Quiet)) {
    throw "WSL OpenSSH is not reachable on 127.0.0.1:22. Complete the WSL Ubuntu wizard first."
}
$wslAddresses = ((& wsl.exe --distribution $WslDistribution --exec hostname -I) | Out-String).Trim()
$wslSourceIp = @($wslAddresses -split "\s+" | Where-Object {
    $_ -match "^([0-9]{1,3}\.){3}[0-9]{1,3}$" -and $_ -ne "127.0.0.1"
}) | Select-Object -First 1
if (-not $wslSourceIp) {
    throw "WSL did not return a non-loopback IPv4 source address for Training Relay."
}
if (-not (Test-Path -LiteralPath $DoctorPath -PathType Leaf)) {
    throw "CyberRangeCoachDoctor.exe is missing: $DoctorPath"
}

$savedLanMode = $env:CRC_LAN_MODE
$savedTlsEnabled = $env:CRC_TLS_ENABLED
$savedBindHost = $env:CRC_BIND_HOST
$savedDataDir = $env:CRC_DATA_DIR
try {
    $env:CRC_LAN_MODE = "true"
    $env:CRC_TLS_ENABLED = "true"
    $env:CRC_BIND_HOST = "0.0.0.0"
    $env:CRC_DATA_DIR = $DataDir
    $doctor = (& $DoctorPath | Out-String) | ConvertFrom-Json
}
finally {
    $env:CRC_LAN_MODE = $savedLanMode
    $env:CRC_TLS_ENABLED = $savedTlsEnabled
    $env:CRC_BIND_HOST = $savedBindHost
    $env:CRC_DATA_DIR = $savedDataDir
}
if ($doctor.ready -ne $true) {
    $blocked = @($doctor.checks | Where-Object { $_.status -eq "blocked" } | ForEach-Object { $_.id })
    throw "Doctor ready=false. Blocked checks: $($blocked -join ', ')"
}
$linuxDoctorCheck = $doctor.checks | Where-Object { $_.id -eq "linux_vm" } | Select-Object -First 1
if ($linuxDoctorCheck.evidence.stored_relay_source_ip -ne $wslSourceIp -or
    $linuxDoctorCheck.evidence.current_wsl_source_ip -ne $wslSourceIp) {
    throw "Doctor relay source does not match the current WSL IPv4 address $wslSourceIp."
}

[pscustomobject]@{
    ready = $true
    private_profile = $privateProfiles[0].Name
    ca_thumbprint = $ca.Thumbprint
    firewall = "TCP 8443 Private LocalSubnet"
    wsl_ssh = "127.0.0.1:22"
    wsl_relay_source = $wslSourceIp
} | ConvertTo-Json -Depth 3
