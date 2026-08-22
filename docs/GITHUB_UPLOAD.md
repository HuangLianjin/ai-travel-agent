# 上传 GitHub 与云服务器部署

## 一、上传前检查

- [x] `.env` 已在 .gitignore，不会上传 Key
- [x] `data/` 已忽略，数据库不会上传
- [x] `frontend/assets/vue.global.prod.js` 和 lucide 已保留提交

## 二、创建 GitHub 仓库并上传

```bash
cd D:/GitHub/ai-travel-agent

git init
git add .
git commit -m "feat: AI travel agent platform"

# 方式一：GitHub CLI
gh repo create ai-travel-agent --public --source=. --push

# 方式二：网页创建仓库后
git remote add origin https://github.com/你的用户名/ai-travel-agent.git
git branch -M main
git push -u origin main
```

上传后确认仓库里**没有** `.env` 和 `data/`。

## 三、云服务器部署

```bash
rsync -av --exclude data --exclude .venv ./ root@服务器IP:/opt/ai-travel-agent/
cd /opt/ai-travel-agent
cp .env.example .env   # 填好生产 Key
docker compose up -d --build
```

Nginx 反代到 127.0.0.1:8000，certbot 配 HTTPS。详细步骤见 [docs/CHINA_CLOUD_DEPLOY.md](docs/CHINA_CLOUD_DEPLOY.md)。

## 四、部署后的简历链接

```text
GitHub：https://github.com/你的用户名/ai-travel-agent
在线地址：https://travel.你的域名.com（配置 HTTPS 后使用）
```