# 星旅 Agent · 面试问答

## 1. 为什么用多智能体，不直接用一个 Agent？

因为任务类型差异大：景点检索、美食推荐、交通规划、路线优化、质量校验各自需要不同工具和约束。拆开以后可以并行执行、独立重试、单独统计失败，主 Agent 只做理解和调度。

## 2. 子 Agent 并行执行，结果怎么合并？

LangGraph 用 Send 并行派发，每个子 Agent 返回 AgentResult，状态里通过 reducer 合并 agent_results；综合 Agent 再按景点、美食、交通分类汇总，生成结构化行程。

## 3. 一个子 Agent 失败怎么办？

子 Agent 有 try/except，失败会记录 error 和 status；搜索失败会自动降级到下一个 Provider；最终生成不会因为单个来源失败而中断。

## 4. 反思重试怎么实现？

synthesis -> reflect，ReflectionAgent 检查预算、时间、重复、来源、天气等；quality_ok=false 且 retry_count < max_retries 时回流 synthesis，最多 2 次，重试只修正问题项。

## 5. 怎么保证内容真实？

景点和美食来自搜索 + 高德 POI，标题过滤掉攻略盘点文案，可疑标题再交给大模型提取店名；价格标注来源和更新时间，不承诺官方实时价。

## 6. 预算怎么约束？

_recompute_costs 每次重算，_enforce_budget 超预算时删除高消费项；交通和反思重算后都会再次执行预算约束，最终保存前 within_budget 必须为 true。

## 7. 改日期为什么不会重新生成整份行程？

主 Agent 输出 changed_fields，date 变更只触发日期/天气/路线校验，不派发景点和美食子 Agent，旧行程内容会被保留。

## 8. 搜索额度用完怎么办？

WebSearchTool 按 Tavily -> SerpAPI -> Bing -> Google -> Serper -> Brave -> 多平台爬取 -> 内置语料自动降级，结果 24h 缓存。

## 9. 怎么评测？

pytest 11 条单测 + 24 条业务评测 + 24 条主 Agent 评测，覆盖意图、参数、预算、天数、路线、来源、子任务派发。

## 10. 怎么部署？

Dockerfile.prod + docker compose，GitHub Actions 跑 pytest/评测/镜像构建，支持 Render/Railway/云服务器 + Nginx HTTPS。
