# 星旅 Agent · 简历与面试素材

## 零、成品验收快照（2026-08-21）

- GitHub：https://github.com/HuangLianjin/ai-travel-agent
- CI：[GitHub Actions](https://github.com/HuangLianjin/ai-travel-agent/actions/workflows/ci.yml)
- 一键启动：`start.ps1` / `start.sh` / `docker compose up -d --build`
- 测试：pytest 11/11；业务评测 24/24；主 Agent 24/24；40 城真实基准 40/40
- 演示账号：`demo/demo123`、`admin/admin123`
- 在线演示：已部署到云服务器，演示地址面试时提供，不公开在仓库

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
4. 账号安全：邮箱验证、登录限流与失败锁定、refresh token、管理员强制改密、TOTP 2FA、登录审计
4. 工程化：Docker、CI、评测、运行 trace、指标
5. 可靠性：搜索降级、反思重试、预算约束、会话并发修复

## 四、不要写的东西

- 不要写“全自动智能体”
- 不要写“100% 真实价格”
- 不要写“企业级上线”，除非真的部署了
- 不要把 .env 里的 Key 写进简历


## 五、真实运行数据（2026-08-21）

基于 40 个城市真实行程生成基准：

- 生成次数：40
- 成功率：100%（40/40）
- 平均耗时：39.6s
- P95 耗时：47.2s
- 总 Token：150,590
- 预估成本：约 0.79 元（按 DeepSeek 价格估算）

报告文件：`docs/bench_report.json`

## 六、简历附件

- 架构图：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 行程规划截图：`docs/screenshots/plan.png`
- 攻略广场截图：`docs/screenshots/guides.png`
- 管理后台截图：`docs/screenshots/admin.png`
