[CmdletBinding()]
param(
    [string]$WslDistribution = "",
    [string]$OutFile = (Join-Path ([Environment]::GetFolderPath("Desktop")) ("crc-poc-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".json"))
)

# Read-only probe for spec 11.3 Zh/Z (stage D PoC). Changes nothing on the
# machine: no firewall edits, no installs, no apt update, no service restarts.
# Every section catches its own error so one missing tool does not hide the rest.

# Continue: in Windows PowerShell 5.1 a native tool writing to stderr would
# otherwise abort the whole probe.
$ErrorActionPreference = "Continue"
$result = [ordered]@{ probe = "crc-windows-poc/v1"; collected_at = (Get-Date).ToString("o") }

function Section([string]$Name, [scriptblock]$Body) {
    $Error.Clear()
    try {
        $value = & $Body
        if ($null -eq $value -and $Error.Count -gt 0) { $value = @{ error = "$($Error[0])" } }
        $script:result[$Name] = $value
    }
    catch { $script:result[$Name] = @{ error = $_.Exception.Message } }
}

# Empty -WslDistribution means the default distribution, whatever its name.
function Wsl([string]$Command) {
    if ($WslDistribution) {
        $raw = & wsl.exe --distribution $WslDistribution --exec /bin/bash -c $Command 2>$null | Out-String
    } else {
        $raw = & wsl.exe --exec /bin/bash -c $Command 2>$null | Out-String
    }
    $text = ($raw -replace "`0", "").Trim()
    if ($LASTEXITCODE -ne 0) { return "exit=$LASTEXITCODE $text" }
    return $text
}

Section "windows" {
    $os = Get-CimInstance Win32_OperatingSystem
    [ordered]@{ caption = $os.Caption; version = $os.Version; build = $os.BuildNumber; hostname = $env:COMPUTERNAME }
}

Section "ipv4" {
    @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne "127.0.0.1" } | ForEach-Object {
        [ordered]@{ interface = $_.InterfaceAlias; address = $_.IPAddress; prefix = $_.PrefixLength; origin = $_.PrefixOrigin.ToString() }
    })
}

Section "connection_profiles" {
    @(Get-NetConnectionProfile | ForEach-Object {
        [ordered]@{ interface = $_.InterfaceAlias; category = $_.NetworkCategory.ToString(); ipv4 = $_.IPv4Connectivity.ToString() }
    })
}

Section "default_routes" {
    @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" | ForEach-Object {
        [ordered]@{ interface = $_.InterfaceAlias; next_hop = $_.NextHop; metric = $_.RouteMetric }
    })
}

Section "listening" {
    @(Get-NetTCPConnection -State Listen | Where-Object { @(22, 3000, 8080, 8443) -contains $_.LocalPort -or ($_.LocalPort -ge 47000 -and $_.LocalPort -le 47100) } | ForEach-Object {
        $name = (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        [ordered]@{ address = $_.LocalAddress; port = $_.LocalPort; process = $name }
    })
}

Section "docker" {
    $lines = & docker.exe ps --all --format "{{.Names}}|{{.Status}}|{{.Ports}}" 2>$null | Out-String
    @($lines.Trim() -split "`r?`n" | Where-Object { $_ })
}

Section "firewall_rules" {
    @(Get-NetFirewallRule -PolicyStore ActiveStore | Where-Object {
        $_.DisplayName -like "CyberLab*" -or $_.DisplayName -like "Cyber Range Coach*"
    } | ForEach-Object {
        $port = $_ | Get-NetFirewallPortFilter
        $address = $_ | Get-NetFirewallAddressFilter
        [ordered]@{
            name = $_.DisplayName; enabled = $_.Enabled.ToString(); direction = $_.Direction.ToString()
            action = $_.Action.ToString(); profile = $_.Profile.ToString()
            protocol = "$($port.Protocol)"; local_port = @($port.LocalPort); remote_address = @($address.RemoteAddress)
        }
    })
}

Section "hyperv_firewall_wsl" {
    if (Get-Command Get-NetFirewallHyperVVMSetting -ErrorAction SilentlyContinue) {
        @(Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore | ForEach-Object {
            [ordered]@{ name = $_.Name; enabled = "$($_.Enabled)"; inbound = "$($_.DefaultInboundAction)"; loopback = "$($_.LoopbackEnabled)" }
        })
    } else { "cmdlet not available" }
}

Section "sshd_service" {
    $service = Get-Service -Name sshd -ErrorAction SilentlyContinue
    if ($null -eq $service) { "not installed" } else { [ordered]@{ status = $service.Status.ToString(); start = $service.StartType.ToString() } }
}

Section "wsl" {
    $config = Join-Path $env:USERPROFILE ".wslconfig"
    [ordered]@{
        version = ((& wsl.exe --version 2>$null | Out-String) -replace "`0", "").Trim()
        distributions = ((& wsl.exe --list --verbose 2>$null | Out-String) -replace "`0", "").Trim()
        wslconfig = if (Test-Path -LiteralPath $config) { Get-Content -LiteralPath $config -Raw } else { "absent" }
        addresses = Wsl "hostname -I"
        routes = Wsl "ip route"
        nameserver = Wsl "grep -m1 ^nameserver /etc/resolv.conf"
        whoami = Wsl "whoami"
    }
}

# How WSL reaches the range on Windows: via localhost (mirrored mode), via the
# gateway (NAT mode) or via the LAN address. Plain TCP connect, 3 s timeout.
# The relay port range 47000-47100 is not probed here: opening a listener could
# make Windows Firewall ask about PowerShell and store a rule. The academy
# checks relay reachability itself when it starts a relay; this probe only
# collects the facts it depends on (networking mode, Hyper-V firewall, rules).
Section "wsl_reachability" {
    $gateway = Wsl "ip route | awk '/^default/ {print `$3; exit}'"
    $lan = $null
    $route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Sort-Object { $_.RouteMetric + (Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4).InterfaceMetric } |
        Select-Object -First 1
    if ($null -ne $route) {
        $lan = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex |
            Select-Object -First 1 -ExpandProperty IPAddress)
    }
    $checks = @()
    foreach ($target in @("127.0.0.1", $gateway, $lan) | Where-Object { $_ }) {
        foreach ($port in 8080, 3000, 8443) {
            $state = Wsl "timeout 3 bash -c '</dev/tcp/$target/$port' 2>/dev/null && echo open || echo closed"
            $checks += [ordered]@{ from = "wsl"; to = $target; port = $port; state = $state }
        }
    }
    [ordered]@{ gateway = $gateway; lan = $lan; checks = $checks }
}

Section "packages_windows" {
    if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
        $list = & winget.exe list --disable-interactivity 2>$null | Out-String
        $list.Trim()
    } else { "winget not available" }
}

Section "packages_wsl" {
    [ordered]@{
        count = Wsl "dpkg-query -W -f='.' | wc -c"
        tools = Wsl "for t in nmap curl nc ssh python3 git tcpdump jq; do printf '%s=' `$t; command -v `$t >/dev/null && echo yes || echo no; done"
        upgradable_from_cache = Wsl "apt list --upgradable 2>/dev/null | tail -n +2 | wc -l"
        installed = Wsl "dpkg-query -W -f='`${Package} `${Version}\n'"
    }
}

$json = $result | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($OutFile, $json, [System.Text.UTF8Encoding]::new($false))
Write-Output "Saved: $OutFile"
Write-Output "Send this one file to the Mac. Nothing on this machine was changed."
