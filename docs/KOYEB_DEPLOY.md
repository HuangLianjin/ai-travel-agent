# Koyeb 免绑卡部署

Koyeb 免费额度支持 1 个 Docker Web Service，多数账号不需要绑卡。

## 1. 创建服务

1. 打开 https://app.koyeb.com 注册/登录，连接 GitHub。
2. 点 `Create Web Service`。
3. 部署方式选 `GitHub`，选择仓库 `HuangLianjin/ai-travel-agent`，分支 `main`。
4. Builder 选 `Dockerfile`，位置保持仓库根目录。
5. Instance 选免费档（通常是 `nano` 或 Free）。
6. Region 选离你近的可用区。

## 2. 环境变量

在 Service 的 Environment 里添加：

```text
OPENAI_API_KEY
TAVILY_API_KEY
MAP_MCP_API_KEY
QWEATHER_API_KEY
QWEATHER_API_HOST
ADMIN_INIT_PASSWORD
DEMO_SEED_ENABLED=true
```

## 3. 部署

点 `Deploy`，等构建完成。

访问地址格式：

```text
https://你的服务名-你的组织名.koyeb.app
```

演示账号：`demo / demo123`。

注意：免费服务闲置后会休眠，第一次打开可能要等几十秒。
