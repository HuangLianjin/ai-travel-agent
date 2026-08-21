# 星旅 Agent · AI 旅行规划平台

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

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --port 8000
```

打开 http://localhost:8000 即可使用。也可以直接运行 `./start.ps1` 或 `./start.sh` 一键启动。

Docker 启动：

```bash
docker compose up -d --build
```

## 演示账号

- 普通用户：`demo` / `demo123`
- 管理员：`admin` / `admin123`

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

## 注意

`.env` 和 `data/` 已在 .gitignore 中，上传 GitHub 时不会包含真实 Key 和数据库。
