# Hugging Face Spaces 免绑卡部署

适合不想给 Render 绑卡、只做面试演示的场景。免费，不用信用卡。

## 1. 创建 Space

1. 打开 https://huggingface.co 注册/登录。
2. 右上角头像 -> `New Space`。
3. Space name 填 `ai-travel-agent`。
4. SDK 选 `Docker`，License 随意。
5. 点 `Create Space`。

## 2. 上传代码

Hugging Face Docker Space 固定读取仓库根目录的 `Dockerfile`，本项目根目录 `Dockerfile` 已支持：

```powershell
cd D:/GitHub/ai-travel-agent
git remote add hf https://huggingface.co/spaces/你的用户名/ai-travel-agent
git push hf main:main
```

## 3. 配置环境变量

进入 Space 的 `Settings -> Variables and secrets`，添加：

```text
OPENAI_API_KEY
TAVILY_API_KEY
MAP_MCP_API_KEY
QWEATHER_API_KEY
QWEATHER_API_HOST
ADMIN_INIT_PASSWORD
DEMO_SEED_ENABLED=true
```

## 4. 等待构建

Space 构建完成后访问：

```text
https://你的用户名-ai-travel-agent.hf.space
```

注意：免费 Space 长时间不用会休眠，第一次打开可能需要 1-2 分钟唤醒。
