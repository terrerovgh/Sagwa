# Run as the existing tufinfra boot task after WSL infra has started.
$ErrorActionPreference = 'Stop'
$addresses = (& wsl.exe -d infra -u root -- hostname -I | Out-String).Trim().Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar infra.' }
$guest = $addresses | Where-Object { $_ -match '^172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+$' } | Select-Object -First 1
if (-not $guest) { throw 'No se encontro IPv4 de WSL infra.' }
$lan = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -eq '192.168.4.64' }
if (-not $lan) { throw 'La direccion LAN configurada no esta disponible.' }
& netsh.exe interface portproxy delete v4tov4 listenaddress=192.168.4.64 listenport=9443 | Out-Null
& netsh.exe interface portproxy add v4tov4 listenaddress=192.168.4.64 listenport=9443 connectaddress=$guest connectport=9443
if ($LASTEXITCODE -ne 0) { throw 'Fallo la actualizacion del relay AgentShell.' }
if (-not (Get-NetFirewallRule -Name AgentShell-Gateway -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name AgentShell-Gateway -DisplayName AgentShell-Gateway -Direction Inbound -Action Allow -Protocol TCP -LocalAddress 192.168.4.64 -LocalPort 9443 -RemoteAddress LocalSubnet | Out-Null
}
