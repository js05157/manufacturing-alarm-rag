param(
    [string]$ServerExe = '',
    [string]$ModelPath = '',
    [ValidateRange(0, 65535)][int]$Port = 0,
    [ValidateRange(512, 4096)][int]$ContextSize = 4096,
    [ValidateRange(0, 128)][int]$Threads = 0,
    [ValidateRange(1, 600)][int]$StartupTimeout = 180,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

function Get-LocalSetting([string]$Name, [string]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
    $envPath = Join-Path $projectRoot '.env'
    if (Test-Path -LiteralPath $envPath) {
        foreach ($line in [IO.File]::ReadAllLines($envPath)) {
            if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*?)\s*$')) {
                $value = $Matches[1].Trim('"').Trim("'")
                if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
            }
        }
    }
    return $Default
}

if (-not $ServerExe) { $ServerExe = Get-LocalSetting 'LLAMA_SERVER_PATH' 'C:\llama.cpp\llama-b11900-bin-win-cpu-x64\llama-server.exe' }
if (-not $ModelPath) { $ModelPath = Get-LocalSetting 'LOCAL_LLM_MODEL_PATH' 'C:\AI\models\qwen3-4b\Qwen3-4B-Q4_K_M.gguf' }
if ($Port -eq 0) { $Port = [int](Get-LocalSetting 'LOCAL_LLM_PORT' '8080') }
if (-not $PSBoundParameters.ContainsKey('ContextSize')) { $ContextSize = [int](Get-LocalSetting 'LOCAL_LLM_CONTEXT' '4096') }
if ($Port -lt 1 -or $Port -gt 65535) { throw 'LOCAL_LLM_PORT must be between 1 and 65535.' }
if ($ContextSize -lt 512 -or $ContextSize -gt 4096) { throw 'LOCAL_LLM_CONTEXT must be between 512 and 4096.' }
if (-not (Test-Path -LiteralPath $ServerExe -PathType Leaf)) { throw "llama-server.exe not found: $ServerExe" }
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) { throw "GGUF model not found: $ModelPath. No model will be downloaded." }
$ServerExe = (Resolve-Path -LiteralPath $ServerExe).Path
$ModelPath = (Resolve-Path -LiteralPath $ModelPath).Path
$modelAlias = Get-LocalSetting 'LOCAL_LLM_MODEL' 'qwen3-4b'
if ($modelAlias -notmatch '^[a-zA-Z0-9._-]{1,64}$') { throw 'LOCAL_LLM_MODEL alias may contain only letters, digits, dot, underscore and hyphen.' }
$baseUrl = "http://127.0.0.1:$Port"

function Get-VerifiedServer {
    $health = Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 3
    $props = Invoke-RestMethod -Uri "$baseUrl/props" -TimeoutSec 3
    $models = Invoke-RestMethod -Uri "$baseUrl/v1/models" -TimeoutSec 3
    if ($health.status -ne 'ok') { throw 'llama.cpp model is not ready.' }
    if ($props.model_path -ne $ModelPath) { throw "Existing server uses another model: $($props.model_path)" }
    if ($props.default_generation_settings.n_ctx -ne $ContextSize) { throw 'Existing server has a different context size.' }
    if ($props.total_slots -ne 1) { throw 'Existing server must use --parallel 1 for the full context budget.' }
    if ($modelAlias -notin @($models.data.id)) { throw 'Existing server has a different model alias.' }
    return $props
}

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    if (@($listeners | Where-Object { $_.LocalAddress -ne '127.0.0.1' }).Count -gt 0) {
        throw "Port $Port is already bound outside 127.0.0.1. No process was stopped."
    }
    foreach ($listener in $listeners) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($owner.ExecutablePath -ne $ServerExe) { throw "Port $Port is already used by another process (PID $($listener.OwningProcess)). No process was stopped." }
        if ($owner.CommandLine -notmatch '(?i)--gpu-layers\s+0(?:\s|$)') { throw 'Existing server CPU-only configuration cannot be verified. No process was stopped.' }
    }
    Get-VerifiedServer | Out-Null
    Write-Output "Existing llama.cpp server is healthy: $baseUrl; model=$modelAlias; context=$ContextSize. Reused without restarting."
    exit 0
}
if ($CheckOnly) { throw "No llama.cpp server is listening at $baseUrl. Run scripts/start_llm.ps1 first." }
if ($Threads -eq 0) {
    $physicalCores = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum
    $Threads = [int][Math]::Max(1, [Math]::Min(6, $physicalCores))
}
$logDirectory = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdout = Join-Path $logDirectory "llama-$stamp.out.log"
$stderr = Join-Path $logDirectory "llama-$stamp.err.log"
$llamaArguments = @(
    '--model', ('"{0}"' -f $ModelPath), '--alias', $modelAlias,
    '--host', '127.0.0.1', '--port', "$Port", '--ctx-size', "$ContextSize",
    '--gpu-layers', '0', '--parallel', '1', '--threads', "$Threads",
    '--threads-batch', "$Threads", '--batch-size', '512', '--ubatch-size', '128',
    '--jinja', '--reasoning', 'off', '--no-context-shift'
)
$serverProcess = Start-Process -FilePath $ServerExe -ArgumentList $llamaArguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
Write-Output "Starting llama.cpp PID $($serverProcess.Id), CPU threads=$Threads, context=$ContextSize, GPU layers=0, parallel=1"
$deadline = (Get-Date).AddSeconds($StartupTimeout)
do {
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) { throw "llama-server exited with code $($serverProcess.ExitCode). Inspect $stderr" }
    try {
        Get-VerifiedServer | Out-Null
        Write-Output "Ready: $baseUrl/v1/chat/completions; model=$modelAlias"
        Write-Output "Logs: $stderr"
        exit 0
    } catch {
        if ((Get-Date) -ge $deadline) { throw "Startup verification timed out; process was left running for inspection. Inspect $stderr. Last status: $($_.Exception.Message)" }
        Start-Sleep -Milliseconds 500
    }
} while ($true)
