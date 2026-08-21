# 星旅 Agent · 简历与面试素材

## 一、简历项目描述模板

```text
AI 旅行规划平台（可在线演示）

基于 FastAPI + LangGraph 构建多智能体行程规划系统，
主 Agent 负责意图识别、参数提取与任务拆解，
景点/美食/交通/路线/反思子 Agent 并行执行，
支持流式输出、多轮局部调整与版本化。

技术栈：Python、FastAPI、LangGraph、SQLite、RAG、SSE、
高德地图 API、和风天气、Tavily/SerpAPI、Docker、GitHub Actions
```

## 二、可量化成果

- 24 条业务离线评测 + 24 条主 Agent 评测，通过率 100%
- pytest 11/11 通过
- 搜索链路支持 7 个 Provider 自动降级 + 24h 缓存
- 局部调整按 changed_fields 最小化派发，减少 token 成本
- 反思重试 + 预算强约束 + 来源约束
- 每次生成保存 agent_runs：token、耗时、状态、错误

## 三、可以重点写的 5 个亮点

1. 真实业务闭环：AI 规划 -> 多轮调整 -> 审核 -> 社区 -> 收藏
2. 多智能体：1 个主 Agent + 5 个子 Agent
3. 真实数据：搜索 + 高德 + 和风天气 + 攻略正文抓取
4. 工程化：Docker、CI、评测、运行 trace、指标
5. 可靠性：搜索降级、反思重试、预算约束、会话并发修复

## 四、不要写的东西

- 不要写“全自动智能体”
- 不要写“100% 真实价格”
- 不要写“企业级上线”，除非真的部署了
- 不要把 .env 里的 Key 写进简历


## 五、真实运行数据（2026-08-21）

基于 20 个城市真实行程生成基准：

- 生成次数：20
- 成功率：100%（20/20）
- 平均耗时：28.1s
- P95 耗时：37.8s
- 总 Token：75,475
- 预估成本：约 0.39 元（按 DeepSeek 价格估算）

报告文件：`docs/bench_report.json`

## 六、简历附件

- 架构图：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 行程规划截图：`docs/screenshots/plan.png`
- 攻略广场截图：`docs/screenshots/guides.png`
- 管理后台截图：`docs/screenshots/admin.png`
