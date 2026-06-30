$ErrorActionPreference = "Stop"

param(
  [string]$TargetIp = "192.168.200.254",
  [int]$ListenPort = 8080,
  [int]$TargetPort = 8443,
  [switch]$SkipLocalhost
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

function Reset-PortProxy {
  param(
    [string]$Ip,
    [int]$LPort,
    [int]$TPort,
    [bool]$IncludeLocalhost
  )

  # Remove regras antigas da porta de escuta.
  & netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$LPort | Out-Null
  & netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$LPort | Out-Null

  # Regra para rede/local IP da maquina.
  & netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$LPort connectaddress=$Ip connectport=$TPort | Out-Null

  # Regra explicita para localhost (opcional).
  if ($IncludeLocalhost) {
    & netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=$LPort connectaddress=$Ip connectport=$TPort | Out-Null
  }
}

function Show-Rule {
  param([int]$LPort)
  Write-Host "`nRegras ativas para a porta $LPort:"
  & netsh interface portproxy show v4tov4 | Select-String -Pattern "$LPort|Endereco|Address|Listen"
}

function Test-Https {
  param([int]$LPort)
  [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
  try {
    $res = Invoke-WebRequest -Uri "https://localhost:$LPort" -UseBasicParsing -TimeoutSec 12
    Write-Host "`nTeste HTTPS localhost:$LPort => $($res.StatusCode)"
  } catch {
    Write-Warning "`nTeste HTTPS localhost:$LPort falhou: $($_.Exception.Message)"
  }
}

Require-Admin
Ensure-Iphlpsvc
Ensure-FirewallPort8443

$includeLocalhost = -not $SkipLocalhost.IsPresent
Reset-PortProxy -Ip $TargetIp -LPort $ListenPort -TPort $TargetPort -IncludeLocalhost $includeLocalhost
Show-Rule -LPort $ListenPort
Test-Https -LPort $ListenPort

Write-Host ""
Write-Host "Concluido: $ListenPort -> $TargetIp`:$TargetPort"
