$ErrorActionPreference = "Stop"

param(
  [string]$Distro = "Ubuntu-22.04",
  [string]$LanIp = "192.168.200.254",
  [int]$Port = 8443
)

function Require-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $p = New-Object Security.Principal.WindowsPrincipal($id)
  if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Abra o PowerShell como Administrador."
  }
}

function Get-WslIp {
  param([string]$UseDistro)
  $ip = wsl -d $UseDistro -- bash -lc "hostname -I | awk '{print \$1}'" 2>$null
  $ip = ($ip | Out-String).Trim()
  if (-not $ip) { throw "Nao consegui obter IP do WSL." }
  return $ip
}

Require-Admin

$wslIp = Get-WslIp -UseDistro $Distro
Write-Host "WSL IP: $wslIp"

# Garante servico de portproxy.
Set-Service iphlpsvc -StartupType Automatic
Start-Service iphlpsvc

# Limpa regras antigas da porta.
foreach ($addr in @("0.0.0.0", "127.0.0.1", $LanIp)) {
  & netsh interface portproxy delete v4tov4 listenaddress=$addr listenport=$Port | Out-Null
}

# Recria regras externas e locais.
& netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$Port connectaddress=$wslIp connectport=$Port | Out-Null
& netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=$Port connectaddress=$wslIp connectport=$Port | Out-Null

# Firewall allow explicito para a porta.
$inRule = "RioBranco 8443 In Any"
$outRule = "RioBranco 8443 Out Any"
Get-NetFirewallRule -DisplayName $inRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
Get-NetFirewallRule -DisplayName $outRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $inRule -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Any | Out-Null
New-NetFirewallRule -DisplayName $outRule -Direction Outbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Any | Out-Null

Write-Host ""
Write-Host "Portproxy ativo:"
& netsh interface portproxy show v4tov4 | Select-String -Pattern "$Port|Endereco|Address|Listen"

Write-Host ""
Write-Host "Listeners locais da porta:"
& netstat -ano | Select-String -Pattern ":$Port\\s+.*LISTENING"

Write-Host ""
Write-Host "Teste local em localhost:"
try {
  [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
  $r = Invoke-WebRequest -Uri "https://localhost:$Port" -UseBasicParsing -TimeoutSec 10
  Write-Host "HTTPS localhost OK => $($r.StatusCode)"
} catch {
  Write-Warning "localhost falhou: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Teste no IP LAN local:"
try {
  [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
  $r2 = Invoke-WebRequest -Uri "https://$LanIp`:$Port" -UseBasicParsing -TimeoutSec 10
  Write-Host "HTTPS $LanIp OK => $($r2.StatusCode)"
} catch {
  Write-Warning "$LanIp falhou: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Concluido. Se ainda nao abrir de outra maquina, validar roteador/VLAN entre cliente e 192.168.200.254."
