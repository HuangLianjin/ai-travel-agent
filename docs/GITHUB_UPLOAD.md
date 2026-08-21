# 上传 GitHub 与在线演示

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

## 三、在线演示

### 方式 A：Render（最快）

1. 打开 https://render.com 注册并连接 GitHub。
2. 推荐 New -> Blueprint：选择本仓库，`render.yaml` 会被自动识别。
3. 也可以 New -> Web Service -> Runtime 选 Docker，Dockerfile 填 `Dockerfile.prod`。
4. 在 Environment 里填：
   - SECRET_KEY
   - LLM_MODE=openai
   - OPENAI_API_KEY
   - OPENAI_BASE_URL=https://api.deepseek.com/v1
   - MODEL_NAME=deepseek-chat
   - TAVILY_API_KEY
   - SERPAPI_API_KEY
   - MAP_MCP_API_KEY
   - QWEATHER_API_KEY
   - QWEATHER_API_HOST
   - ADMIN_INIT_PASSWORD
   - DEMO_SEED_ENABLED=false
   - MAIL_ENABLED=false
5. 部署后打开 Render 分配的 URL。

注意：Render 免费实例没有持久磁盘，SQLite 数据重启后会清空，适合演示，不适合正式存储。

### 方式 B：云服务器 + Docker + Nginx

```bash
rsync -av --exclude data --exclude .venv ./ root@服务器IP:/opt/ai-travel-agent/
cd /opt/ai-travel-agent
docker compose up -d --build
```

Nginx 反代到 127.0.0.1:8000，certbot 配 HTTPS。

### 方式 C：Railway

Railway 也支持 Docker 部署，且有免费额度；配置同样的环境变量即可。

## 四、部署后的简历链接

```text
在线演示：https://ai-travel-agent.onrender.com
GitHub：https://github.com/你的用户名/ai-travel-agent
```
