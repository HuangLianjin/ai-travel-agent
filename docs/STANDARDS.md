# 六大硬核标准落地对照

## 1. 解决真实问题

业务场景是“AI 行程规划平台”：从出发地、日期、同行人数、预算、交通方式、兴趣标签构建规划状态，输出按 Day 拆分的主题、景点、活动、餐饮、交通与建议游玩时长。

证据：
- `app/services/planner.py`：参数提取、意图识别、行程生成
- `app/corpus.py`：北京 / 成都 / 上海真实语料
- `frontend/app.js`：行程规划、攻略广场、收藏、管理后台

## 2. 完整后端工程体系

FastAPI + LangGraph + SQLite 分层实现，包含认证、RBAC、审计、限流、会话、版本化、静态前端服务。

证据：
- `app/main.py`：应用生命周期
- `app/api/routes.py`：认证、对话、行程、社区、审核、指标
- `app/db.py`：用户、行程、版本、攻略、审核、审计
- `app/deps.py`：JWT + RBAC

## 3. Agent 真正的核心能力

LangGraph StateGraph 编排多节点：

```
main_parse -> main_plan -> dispatch(Send) -> route -> validate -> synthesis -> finish
      └-> adjust(局部重规划) ----------------> finish
```

支持多轮对话调整、参数补全、局部重规划、冲突检查，避免每次全量重生成。

证据：
- `app/agent/multi_graph.py`
- `app/services/planner.py::apply_adjustment`

## 4. 上下文工程

- 会话历史持久化到 `conversations`
- 行程按版本保存到 `itinerary_versions`
- 调整时加载历史行程参数，只 patch 变化部分
- 知识检索使用关键词 + 字符向量混合召回，结果带来源

证据：
- `app/db.py::upsert_conversation`
- `app/rag/search.py`

## 5. 可观测性与评测体系

- 进程内指标：请求成功率、P95 延迟、阶段计数、工具计数、失败类型
- `GET /api/metrics`
- 24 条业务评测 + 24 条主 Agent TaskPlan 评测，覆盖创建 / 调整 / 咨询 / 闲聊
- `python -m app.eval.runner --output data/eval_report.json`
- 当前结果：业务 24/24，主 Agent 24/24，通过率 100%

证据：
- `app/observability/metrics.py`
- `app/eval/cases.py`
- `app/eval/runner.py`

## 6. 人机协同

- AI 生成的行程默认 `draft`
- 自动创建人工复核任务
- 管理员审核通过后用户才能发布
- 社区攻略同样走“机器生成 / 用户提交 → 人工审核”
- 管理员可禁言、封禁、配置推荐位

证据：
- `app/db.py::create_review`
- `app/api/routes.py::admin_reviews`
- `frontend/app.js` 管理后台

