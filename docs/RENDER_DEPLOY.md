# Render 在线部署步骤

## 1. 准备

- GitHub 仓库已推送：https://github.com/HuangLianjin/ai-travel-agent
- GitHub Actions CI 已通过（会自动构建 `Dockerfile.prod`）

## 2. 创建服务

1. 打开 https://render.com 注册或登录，并点击右上角头像连接 GitHub。
2. 进入 Dashboard，点 `New -> Blueprint`。
3. 选择仓库 `HuangLianjin/ai-travel-agent`，点 `Apply`。
4. Render 会自动读取 `render.yaml`，创建名为 `ai-travel-agent` 的 Web Service。
5. 在刚创建的服务页面左侧点 `Environment`，补上以下变量：

```text
OPENAI_API_KEY=你的 DeepSeek Key
TAVILY_API_KEY=你的 Tavily Key（或 SERPAPI_API_KEY）
MAP_MCP_API_KEY=你的高德 Key
QWEATHER_API_KEY=你的和风天气 Key
QWEATHER_API_HOST=你的和风天气 Host
ADMIN_INIT_PASSWORD=你的管理员初始密码
DEMO_SEED_ENABLED=true
```

6. 点 `Manual Deploy -> Deploy latest commit`。

## 3. 验证

- 部署完成后打开 `https://ai-travel-agent.onrender.com`
- 健康检查：`https://ai-travel-agent.onrender.com/api/health`
- 演示账号：`demo / demo123`（因为 `DEMO_SEED_ENABLED=true`）
- 管理员：首次登录会强制修改密码

## 4. 注意事项

- Render 免费实例闲置 15 分钟后会休眠，第一次访问可能需要等待 30-60 秒。
- 免费实例没有持久磁盘，SQLite 数据和上传文件在重新部署后会清空，只适合演示。
- 正式上线请升级 PostgreSQL + 云数据库 + 备份。
