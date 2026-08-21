# 一键推送 GitHub：先检查 gh，再创建公开仓库并推送
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path) + "/.."

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "未检测到 GitHub CLI，请先安装："
    Write-Host "winget install --id GitHub.cli"
    Write-Host "然后运行: gh auth login"
    exit 1
}

gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "请先登录: gh auth login"
    exit 1
}

if (-not (Test-Path .git)) {
    git init -b main
}
git add .
git commit -m "feat: AI travel agent platform" --allow-empty
gh repo create ai-travel-agent --public --source=. --push --description "AI travel agent platform with multi-agent, RAG, real data and eval"
Write-Host "推送完成"
