$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (Test-Path ".venv\Scripts\python.exe") {
  $python = ".venv\Scripts\python.exe"
} else {
  $python = "python"
}

if (-not (Test-Path "data\travel.db")) {
  & $python -m app.seed
}

& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

