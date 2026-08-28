[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Agent,

    [Parameter(Mandatory = $true)]
    [string]$Config,

    [string]$InstallRoot = "$env:ProgramData\NanotechSoft\Backup"
)

$ErrorActionPreference = "Stop"

function Quote-TaskArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Execute este instalador em um PowerShell aberto como Administrador."
}

$agentSource = (Resolve-Path -LiteralPath $Agent).Path
$configSource = (Resolve-Path -LiteralPath $Config).Path
$bootstrap = Get-Content -LiteralPath $configSource -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $bootstrap.agentId) {
    throw "O JSON informado não possui agentId."
}

$agentId = [string]$bootstrap.agentId
if ($agentId -notmatch '^[A-Za-z0-9._-]+$') {
    throw "O agentId do JSON é inválido."
}

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$pythonPrefix = @()
if (-not $pythonCommand) {
    $pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    $pythonPrefix = @("-3")
}
if (-not $pythonCommand) {
    throw "Python 3 não foi encontrado. Instale-o para todos os usuários e execute novamente."
}

$credential = Get-Credential -UserName "$env:COMPUTERNAME\administrator" -Message "Conta que lerá as origens e gravará no HDD"
$installDirectory = Join-Path $InstallRoot $agentId
$agentTarget = Join-Path $installDirectory "technology_backup_agent.py"
$configTarget = Join-Path $installDirectory "plan.json"
$stateTarget = Join-Path $installDirectory "plan.state.json"

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Copy-Item -LiteralPath $agentSource -Destination $agentTarget -Force
Copy-Item -LiteralPath $configSource -Destination $configTarget -Force

# A configuração contém o token do agente. Somente SYSTEM e administradores
# locais permanecem com acesso ao diretório.
& icacls.exe $installDirectory /inheritance:r | Out-Null
& icacls.exe $installDirectory /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Não foi possível proteger $installDirectory com icacls."
}

$validateArguments = @($pythonPrefix) + @($agentTarget, "--config", $configTarget, "--validate")
& $pythonCommand.Source @validateArguments
if ($LASTEXITCODE -ne 0) {
    throw "O agente não validou o JSON. A tarefa não foi criada."
}

$taskName = "NanotechSoft Backup $agentId"
$taskArguments = (@($pythonPrefix) + @($agentTarget, "--config", $configTarget) |
    ForEach-Object { Quote-TaskArgument $_ }) -join " "
$action = New-ScheduledTaskAction -Execute $pythonCommand.Source -Argument $taskArguments -WorkingDirectory $installDirectory
$trigger = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Minutes 2)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -User $credential.UserName `
        -Password $plainPassword `
        -RunLevel Highest `
        -Force | Out-Null
} finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    $plainPassword = $null
}

Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 2
$task = Get-ScheduledTask -TaskName $taskName
$taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
Write-Host "Agente instalado em: $installDirectory"
Write-Host "Tarefa: $taskName ($($task.State))"
Write-Host "Último resultado: $($taskInfo.LastTaskResult)"
Write-Host "Estado local: $stateTarget"
