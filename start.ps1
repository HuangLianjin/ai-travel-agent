$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 首次运行自动补齐环境：.env、venv、依赖、演示数据
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "[start] 已生成 .env（默认 demo 模式，可后续填入真实 Key）"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "[start] 未检测到 .venv，正在创建虚拟环境..."
  python -m venv .venv
  Write-Host "[start] 正在安装依赖..."
  & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
}

$python = ".venv\Scripts\python.exe"

if (-not (Test-Path "data\travel.db")) {
  Write-Host "[start] 正在初始化演示数据..."
  & $python -m app.seed
}

Write-Host "[start] 启动服务: http://127.0.0.1:8000"
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

