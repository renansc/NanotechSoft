$ErrorActionPreference = "Stop"

param(
  [string]$Distro = "Ubuntu-22.04",
  [string]$ProjectPath = "/srv/RioBranco",
  [string]$LogPath = "/tmp/riobranco_https_8443.log",
  [string]$CertDir = "/srv/RioBranco/certs",
  [string]$CertFile = "/srv/RioBranco/certs/dev.crt",
  [string]$KeyFile = "/srv/RioBranco/certs/dev.key"
)

function Require-Admin {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Execute este script no PowerShell como Administrador."
  }
}

function Ensure-Iphlpsvc {
  $svc = Get-Service -Name iphlpsvc -ErrorAction Stop
  if ($svc.Status -ne "Running") {
    Start-Service -Name iphlpsvc
  }
}

function Ensure-FirewallPort8443 {
  $ruleNameIn = "RioBranco HTTPS 8443 In"
  $ruleNameOut = "RioBranco HTTPS 8443 Out"

  if (-not (Get-NetFirewallRule -DisplayName $ruleNameIn -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleNameIn -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 | Out-Null
  }
  if (-not (Get-NetFirewallRule -DisplayName $ruleNameOut -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleNameOut -Direction Outbound -Action Allow -Protocol TCP -LocalPort 8443 | Out-Null
  }
}

function Get-WslIp {
  param([string]$UseDistro)
  $ip = wsl -d $UseDistro -- bash -lc "hostname -I | awk '{print \$1}'" 2>$null
  $ip = ($ip | Out-String).Trim()
  if (-not $ip) {
    throw "Nao foi possivel obter o IP do WSL para '$UseDistro'."
  }
  return $ip
}

function Start-ServerInWsl {
  param(
    [string]$UseDistro,
    [string]$UseProjectPath,
    [string]$UseLogPath,
    [string]$UseCertDir,
    [string]$UseCertFile,
    [string]$UseKeyFile
  )

  $cmd = @"
set -e
cd '$UseProjectPath'
mkdir -p '$UseCertDir'
if [ ! -s '$UseCertFile' ] || [ ! -s '$UseKeyFile' ]; then
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout '$UseKeyFile' -out '$UseCertFile' -subj '/CN=localhost'
fi
pkill -f 'python3 server.py' >/dev/null 2>&1 || true
nohup env APP_PORT=8443 APP_HTTPS=1 APP_SSL_CERT='$UseCertFile' APP_SSL_KEY='$UseKeyFile' \
  python3 server.py > '$UseLogPath' 2>&1 < /dev/null &
echo \$!
"@

  $pid = wsl -d $UseDistro -- bash -lc $cmd
  $pid = ($pid | Out-String).Trim()
  if (-not $pid) {
    throw "Nao foi possivel iniciar o server.py no WSL."
  }
  return $pid
}

function Wait-WslPort8443 {
  param([string]$UseDistro)
  for ($i = 0; $i -lt 12; $i++) {
    $ok = wsl -d $UseDistro -- bash -lc "ss -ltn | grep -q ':8443 ' && echo OK || true"
    if (($ok | Out-String).Trim() -eq "OK") {
      return $true
    }
    Start-Sleep -Seconds 1
  }
  return $false
}

function Set-PortProxy8443 {
  param([string]$WslIp)
  & netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8443 | Out-Null
  & netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=8443 | Out-Null
  & netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8443 connectaddress=$WslIp connectport=8443 | Out-Null
  & netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8443 connectaddress=$WslIp connectport=8443 | Out-Null
}

function Test-LocalHttps8443 {
  [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
  try {
    $res = Invoke-WebRequest -Uri "https://localhost:8443" -UseBasicParsing -TimeoutSec 12
    Write-Host "Teste HTTPS localhost:8443 => $($res.StatusCode)"
  } catch {
    Write-Warning "Teste HTTPS falhou: $($_.Exception.Message)"
  }
}

Require-Admin
Ensure-Iphlpsvc
Ensure-FirewallPort8443

$wslIp = Get-WslIp -UseDistro $Distro
Write-Host "WSL IP atual: $wslIp"

$serverPid = Start-ServerInWsl -UseDistro $Distro -UseProjectPath $ProjectPath -UseLogPath $LogPath -UseCertDir $CertDir -UseCertFile $CertFile -UseKeyFile $KeyFile
Write-Host "server.py iniciado no WSL (PID: $serverPid)"

if (-not (Wait-WslPort8443 -UseDistro $Distro)) {
  Write-Warning "A porta 8443 nao abriu no WSL. Ultimas linhas do log:"
  wsl -d $Distro -- bash -lc "tail -n 60 '$LogPath' || true"
  throw "Falha ao subir servidor em https:8443."
}

Set-PortProxy8443 -WslIp $wslIp
Write-Host "Portproxy configurado: localhost:8443 -> $wslIp:8443"

Test-LocalHttps8443

Write-Host ""
Write-Host "Pronto. Acesse: https://localhost:8443"
Write-Host "Log do servidor: $LogPath"
