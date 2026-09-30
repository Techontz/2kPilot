<#
.SYNOPSIS
  Starts the 2kFX MT5 bridge from its virtual environment.

.DESCRIPTION
  Run from anywhere; the script switches to the mt5_bridge folder so that .env and
  relative paths resolve. Output is appended to logs\bridge.log (JSON lines) when
  -LogToFile is given (useful for Task Scheduler), otherwise it goes to the console.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File C:\mt5_bridge\scripts\start_bridge.ps1
  powershell -ExecutionPolicy Bypass -File C:\mt5_bridge\scripts\start_bridge.ps1 -LogToFile
#>
param(
    [switch]$LogToFile,
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"
$BridgeRoot = Split-Path -Parent $PSScriptRoot
Set-Location $BridgeRoot

$Exe = Join-Path $BridgeRoot ".venv\Scripts\mt5-bridge.exe"
if (-not (Test-Path $Exe)) {
    Write-Error "mt5-bridge not found at $Exe. Create the venv and run: .venv\Scripts\pip install -e ."
    exit 1
}
if (-not (Test-Path (Join-Path $BridgeRoot $EnvFile))) {
    Write-Error "$EnvFile not found in $BridgeRoot. Copy .env.example to .env and fill it in."
    exit 1
}

if ($LogToFile) {
    $LogDir = Join-Path $BridgeRoot "logs"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $Log = Join-Path $LogDir "bridge.log"
    & $Exe --env-file $EnvFile *>> $Log
} else {
    & $Exe --env-file $EnvFile
}
exit $LASTEXITCODE
