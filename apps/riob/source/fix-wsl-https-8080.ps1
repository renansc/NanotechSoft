$ErrorActionPreference = "Stop"

function Require-Admin {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Execute este script no PowerShell como Administrador."
  }
}

function Get-WslIp {
  param(
    [string]$Distro = "Ubuntu-22.04"
  )
  $ip = wsl -d $Distro -- bash -lc "hostname -I | awk '{print \$1}'" 2>$null
  $ip = ($ip | Out-String).Trim()
  if (-not $ip) {
    throw "Nao foi possivel obter o IP do WSL para a distro '$Distro'."
  }
  return $ip
}

function Ensure-Iphlpsvc {
  $svc = Get-Service -Name iphlpsvc -ErrorAction Stop
  if ($svc.Status -ne "Running") {
    Start-Service -Name iphlpsvc
  }
}

function Reset-PortProxy8080 {
  param(
    [string]$WslIp
  )

  # Remove regras conflitantes da 8080.
  & netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8080 | Out-Null
  & netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=8080 | Out-Null

  # Cria regra local para localhost:8080 -> WSL_IP:8080.
  & netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8080 connectaddress=$WslIp connectport=8080 | Out-Null
}

function Show-Rule8080 {
  Write-Host "`nRegras ativas para 8080:"
  & netsh interface portproxy show v4tov4 | Select-String -Pattern "8080|Endereco|Address|Listen"
}

function Test-Https8080 {
  [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
  try {
    $res = Invoke-WebRequest -Uri "https://localhost:8080" -UseBasicParsing -TimeoutSec 12
    Write-Host "`nTeste HTTPS OK: $($res.StatusCode)"
  } catch {
    Write-Warning "`nTeste HTTPS falhou: $($_.Exception.Message)"
    Write-Host "Confirme se o Flask no WSL esta rodando em HTTPS na porta 8080."
  }
}

Require-Admin
Ensure-Iphlpsvc
$wslIp = Get-WslIp -Distro "Ubuntu-22.04"
Write-Host "IP atual do WSL: $wslIp"
Reset-PortProxy8080 -WslIp $wslIp
Show-Rule8080
Test-Https8080

Write-Host "`nConcluido."
