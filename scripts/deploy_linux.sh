#!/usr/bin/env bash
set -euo pipefail

# 国内轻量服务器一键部署脚本（Ubuntu 22.04）
# 用法：sudo bash scripts/deploy_linux.sh

REPO_URL="${REPO_URL:-https://github.com/HuangLianjin/ai-travel-agent.git}"
APP_DIR="${APP_DIR:-/opt/ai-travel-agent}"

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行：sudo bash scripts/deploy_linux.sh"
  exit 1
fi

echo "==> 安装 Docker 与 Compose"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ca-certificates curl gnupg git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-compose-plugin
  systemctl enable --now docker
fi

echo "==> 拉取项目"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch --prune
  git -C "$APP_DIR" reset --hard origin/main
fi
cd "$APP_DIR"

echo "==> 准备环境变量"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 $APP_DIR/.env，请编辑填入 DeepSeek / Tavily / 高德 / 和风天气 Key，以及 ADMIN_INIT_PASSWORD、DEMO_SEED_ENABLED=true"
fi

echo "==> 构建并启动"
docker compose up -d --build

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "部署完成："
echo "  访问地址：http://${IP:-服务器IP}:8000"
echo "  健康检查：http://${IP:-服务器IP}:8000/api/health"
echo "  日志查看：docker compose -f $APP_DIR/docker-compose.yml logs -f app"
echo "  注意：请在云控制台安全组/防火墙放行 8000 端口"
