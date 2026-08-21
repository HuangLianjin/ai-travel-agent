# 星旅 Agent · AI 旅行规划平台

[![CI](https://github.com/HuangLianjin/ai-travel-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/HuangLianjin/ai-travel-agent/actions/workflows/ci.yml)

一个可运行的 AI 行程规划平台成品：FastAPI + LangGraph 主 Agent / 子 Agent 编排 + RAG 混合检索 + 真实搜索/高德地图/和风天气 + 多轮对话调整 + 攻略社区 + RBAC 运营后台 + 可观测指标与离线评测。

## 核心功能

- 1 个主 Agent + 景点/美食/交通/路线/反思 子 Agent
- 搜索链路 7 个 Provider 自动降级 + 24h 缓存
- 攻略正文并发抓取、正文清洗、页面缓存
- 数据可信度分级：官方预约 / 参考 / 估算 / 用户反馈
- 景区/餐厅价格库与用户价格反馈审核
- 高德 POI / 路线 / 地理编码
- 和风天气预报与官方预警
- 多轮局部调整，按 changed_fields 最小化派发
- 反思重试 + 预算强约束 + 来源约束
- 流式输出、版本管理、人工审核、攻略广场、收藏、关注
- 运行 trace：每次生成保存 token、耗时、状态、错误
- Docker + GitHub Actions CI + 离线评测

## 技术栈

Python、FastAPI、LangGraph、SQLite、RAG、SSE、Vue 3、高德地图 API、和风天气、Tavily/SerpAPI、Docker、GitHub Actions

## 快速开始（一键启动）

Windows：

```powershell
.\start.ps1
```

macOS / Linux：

```bash
./start.sh
```

脚本会自动完成：复制 `.env.example` 为 `.env`、创建虚拟环境、安装依赖、初始化演示数据，然后启动服务。打开 http://localhost:8000 即可使用。

默认不创建演示账号；需要体验演示账号时，在 `.env` 里设置 `DEMO_SEED_ENABLED=true`。

Docker 一键启动（不需要本机安装 Python）：

```bash
docker compose up -d --build
```

手动启动：

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --port 8000
```

## 演示账号

- 普通用户：`demo` / `demo123`（需设置 `DEMO_SEED_ENABLED=true` 后自动创建）
- 管理员：通过 `ADMIN_INIT_PASSWORD` 初始化，首次登录强制修改密码，不再提供公开默认密码

## 在线部署（Render）

仓库已包含 `render.yaml` 和 `Dockerfile.prod`。在 Render 连接本仓库后选择 Blueprint 或 Docker Web Service，填入 DeepSeek/Tavily/SerpAPI/高德/和风天气 Key，即可获得公网 HTTPS 演示地址。详细步骤见 [docs/GITHUB_UPLOAD.md](docs/GITHUB_UPLOAD.md)。

## 测试与评测

```bash
python -m pytest tests -q
python -m app.eval.runner --output data/eval_report.json
```

当前结果：pytest 11/11 通过；业务评测 24/24，主 Agent 评测 24/24。

真实 20 城基准：20/20 成功，平均耗时 28.1s，P95 37.8s。

## 架构与截图

- 系统架构：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 行程规划截图：`docs/screenshots/plan.png`
- 攻略广场截图：`docs/screenshots/guides.png`
- 管理后台截图：`docs/screenshots/admin.png`

## 文档

- 上线执行手册：[docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md)
- 多智能体计划：[docs/MULTI_AGENT_PLAN.md](docs/MULTI_AGENT_PLAN.md)
- 优化计划与落地状态：[docs/OPTIMIZATION_PLAN.md](docs/OPTIMIZATION_PLAN.md)
- 生产化升级计划：[docs/PRODUCTION_UPGRADE_PLAN.md](docs/PRODUCTION_UPGRADE_PLAN.md)
- 简历素材：[docs/RESUME_GUIDE.md](docs/RESUME_GUIDE.md)
- 面试问答：[docs/INTERVIEW_Q_A.md](docs/INTERVIEW_Q_A.md)
- 产品思考与面试叙事：[docs/INTERVIEW_NARRATIVE.md](docs/INTERVIEW_NARRATIVE.md)
- GitHub 上传与在线演示：[docs/GITHUB_UPLOAD.md](docs/GITHUB_UPLOAD.md)
- Render 在线部署：[docs/RENDER_DEPLOY.md](docs/RENDER_DEPLOY.md)
- 国内轻量服务器部署：[docs/CHINA_CLOUD_DEPLOY.md](docs/CHINA_CLOUD_DEPLOY.md)

## 注意

- `.env` 和 `data/` 已在 .gitignore 中，上传 GitHub 时不会包含真实 Key 和数据库。
- 一键启动会生成 `.env`，默认 `LLM_MODE=demo`；需要真实规划时填入 DeepSeek/OpenAI 与搜索 Key。
- 安全加固：注册需手机号验证码，登录限流与失败锁定，管理员由 `ADMIN_INIT_PASSWORD` 创建并强制首次改密，支持 TOTP 2FA。
