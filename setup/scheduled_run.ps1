# Scheduled headless run of the LinkedIn auto-applier.
# Loads the optional project-root .env into process environment (secrets stay
# out of source files), then runs runAiBot.py with the project venv.
# Output is appended to logs/scheduled_run_<date>.log.
$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$envFile = Join-Path $projectRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            $value = $Matches[2]
            if ($value.Length -ge 2 -and ($value.StartsWith('"') -and $value.EndsWith('"') -or $value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            [Environment]::SetEnvironmentVariable($Matches[1], $value, "Process")
        }
    }
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$logDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "scheduled_run_$stamp.log"

Add-Content -Path $log -Value "=== run started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
& (Join-Path $projectRoot ".venv\Scripts\python.exe") (Join-Path $projectRoot "runAiBot.py") *>> $log
Add-Content -Path $log -Value "=== run ended $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (exit $LASTEXITCODE) ==="
