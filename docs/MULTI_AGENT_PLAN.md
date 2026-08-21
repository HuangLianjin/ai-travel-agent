# 星旅 Agent 多智能体改造计划书

## 1. 改造目标

把当前“单 Agent 多步骤工作流”升级为：

> 1 个主 Agent 负责任务理解、拆解、调度与汇总，下面挂多个子 Agent 分别完成景点、美食、交通、路线、校验等专项任务。

保留现有业务闭环：AI 规划、多轮调整、版本管理、人工复核、社区、评测与可观测性。

## 2. 总体架构

```
用户输入
   │
   ▼
┌─────────────────────────────┐
│  Main Agent（任务规划/调度）   │
│  parse -> plan -> dispatch   │
└─────────────────────────────┘
   │ 并行 / 按需派发
   ├── AttractionAgent   景点检索
   ├── FoodAgent         美食推荐
   ├── TransportAgent    交通/距离
   ├── RouteAgent        路线优化
   └── ValidatorAgent    校验纠偏
   │
   ▼
┌─────────────────────────────┐
│  SynthesisAgent 汇总成行程     │
│  生成版本 -> 人工复核 -> 发布   │
└─────────────────────────────┘
```

主 Agent 不亲自做所有事情，只负责：

- 理解用户意图
- 提取行程参数
- 拆解成子任务
- 决定哪些子 Agent 并行、哪些串行
- 汇总子 Agent 结果
- 判断是否需要调整或重试

## 3. 智能体清单

| Agent | 职责 | 输入 | 输出 |
|---|---|---|---|
| Main Agent | 意图识别、参数补全、任务拆解、调度 | 用户消息、历史会话、当前行程 | TaskPlan、调度指令 |
| AttractionAgent | 联网检索经典/热门/小众景点并补齐坐标 | 城市、天数、兴趣、预算 | 候选景点列表、来源、坐标 |
| FoodAgent | 推荐经典美食与本地小店 | 城市、兴趣、预算、同行人数 | 每日餐饮建议、来源链接 |
| TransportAgent | 交通枢纽、距离、通行时间 | 城市、景点坐标、出发地 | 交通候选、耗时、换乘建议 |
| RouteAgent | 景点顺序优化、防跨区折返 | 景点、距离矩阵、停留时长 | 每日路线 |
| ValidatorAgent | 来源约束、营业时间、重复、冲突检查 | 行程草稿 | 校验问题列表 |
| SynthesisAgent | 汇总成最终行程 | 各子 Agent 结果 | 结构化行程 |

## 4. 子 Agent 统一协议

每个子 Agent 实现统一接口：

```python
class BaseTravelAgent:
    name: str
    role_prompt: str
    tools: list[Tool]

    async def run(self, subtask: Subtask, context: AgentContext) -> AgentResult
```

`Subtask`：

```python
{
  "task_id": "attraction-001",
  "type": "attraction",
  "params": {"city": "北京", "days": 3, "interests": ["历史"]},
  "input_refs": ["trip-001"]
}
```

`AgentResult`：

```python
{
  "agent": "AttractionAgent",
  "status": "success | retry | failed",
  "data": {...},
  "sources": [...],
  "tool_calls": [...],
  "latency_ms": 123,
  "error": ""
}
```

## 5. 主 Agent 任务规划

Main Agent 第一版使用“规则 + 结构化输出”：

1. 意图分类：`create / adjust / ask / chat`
2. 参数提取：城市、天数、人数、预算、交通、兴趣
3. 生成 `TaskPlan`：

```python
{
  "main_intent": "create",
  "subtasks": [
    {"type": "attraction", "priority": 1, "parallel": true},
    {"type": "food", "priority": 1, "parallel": true},
    {"type": "transport", "priority": 1, "parallel": true},
    {"type": "route", "priority": 2, "parallel": false},
    {"type": "validate", "priority": 3, "parallel": false},
    {"type": "synthesis", "priority": 4, "parallel": false}
  ],
  "retry_policy": {"max_retries": 2, "retry_agents": ["attraction", "route"]}
}
```

## 6. 多轮调整改造

调整请求不再全量重生成，只派发相关子 Agent：

| 用户指令 | 触发子 Agent |
|---|---|
| “当天轻松一些” | RouteAgent + SynthesisAgent |
| “增加火锅” | FoodAgent + SynthesisAgent |
| “推荐附近酒店” | TransportAgent + FoodAgent |
| “去掉长城” | AttractionAgent + RouteAgent |
| “改成自驾” | TransportAgent + RouteAgent |

Main Agent 根据 `adjust` 类型生成局部 TaskPlan，只重算受影响部分，并生成新版本。

## 7. LangGraph 改造

现有 `app/agent/graph.py` 替换为：

```text
START -> main_parse
      -> main_plan
      -> dispatch_subtasks (Send 并行)
         ├── specialist_attraction
         ├── specialist_food
         └── specialist_transport
      -> route_optimize
      -> validate
      -> synthesis
      -> version_writer
      -> END
```

调整模式：

```text
START -> main_parse
      -> main_plan(adjust)
      -> dispatch_partial
      -> route_optimize
      -> validate
      -> synthesis
      -> version_writer
      -> END
```

## 8. 上下文与版本

- Main Agent 读取会话历史和当前行程版本
- 子 Agent 只接收自己需要的上下文片段
- 每次 Synthesis 生成新 `itinerary_version`
- 子 Agent 的 `AgentResult` 全部存入 trace，便于定位失败

## 9. 可观测性与评测升级

### 指标

- 主 Agent 调度次数
- 每个子 Agent 调用次数、成功率、平均耗时
- 子 Agent 失败类型统计
- 局部重规划比例
- 人工复核前/后发布率

### 评测用例

新增用例类型：

| 用例 | 验证点 |
|---|---|
| 主 Agent 任务拆解 | 输入是否生成正确的 TaskPlan |
| AttractionAgent | 是否返回来源约束的景点 |
| FoodAgent | 是否匹配城市和偏好 |
| RouteAgent | 是否优化顺序、减少折返 |
| ValidatorAgent | 是否发现营业时间/重复问题 |
| 调整子任务 | 是否只调用相关子 Agent |

现有 24 条用例保留，新增至少 10 条多智能体协作用例。

## 9.5 联网搜索与地图 MCP

### 联网搜索

- FoodAgent 必须使用联网搜索找“经典美食 / 本地老店 / 必吃榜”，不只依赖内置语料。
- AttractionAgent 必须使用联网搜索找“经典景点 / 热门景点 / 小众拍照点”，不只依赖内置语料。
- 推荐接入：MCP 搜索工具（Tavily / Bing / DuckDuckGo / 自定义搜索服务）。
- 搜索结果必须保留来源标题、链接、摘要，进入 `sources` 字段。
- AttractionAgent 通过地图 MCP 的 POI 检索/地理编码补齐景点经纬度。

### 地图 MCP

- TransportAgent 使用地图 MCP 完成交通规划：
  - 路线规划：起点 -> 景点 -> 终点
  - 距离矩阵：计算景点间通行距离与时间
  - 换乘/驾车/公交耗时
  - 实时交通与区域折返判断
- AttractionAgent 使用地图 MCP 的 POI 检索 / 地理编码，补充景点坐标、地址、营业信息。
- 推荐接入：高德地图 MCP 或 Google Maps MCP，通过统一 `MapMCPTool` 封装。
- 地图结果必须进入 RouteAgent 的路线优化输入。

### 主 Agent 调度约束

- 生成 TaskPlan 时，`food` 子任务必须绑定 `web_search` 工具。
- `attraction` 子任务必须绑定 `web_search` 与 `map_mcp` 的 POI 检索。
- `transport` 子任务必须绑定 `map_mcp` 的路线与距离矩阵。
- 无网络/无 MCP 时可降级到内置语料，但必须在 `AgentResult.tools` 中记录 `fallback`。

## 10. 实施步骤

### Phase 1：Agent 协议

- 新增 `app/agent/agents/base.py`
- 新增 `Subtask / AgentResult / AgentContext`
- 新增工具注册表

### Phase 2：子 Agent

- `AttractionAgent`
- `FoodAgent`
- `TransportAgent`
- `RouteAgent`
- `ValidatorAgent`

### Phase 3：主 Agent

- `MainAgent` 负责意图识别、参数提取、TaskPlan
- 重写 `app/agent/graph.py`
- LangGraph `Send` 并行派发

### Phase 4：Synthesis

- 汇总子 Agent 结果
- 生成版本化行程
- 保留人工复核

### Phase 5：多轮调整

- `adjust` 模式局部派发
- 版本递增

### Phase 6：评测与指标

- 更新 `app/observability/metrics.py`
- 新增子 Agent 评测用例
- 更新 `docs/STANDARDS.md`

### Phase 7：联网搜索与地图 MCP

- 实现统一 `WebSearchTool`（MCP / HTTP 适配器）
- 实现统一 `MapMCPTool`（高德 / Google 双适配）
- FoodAgent 接入联网搜索
- AttractionAgent 接入联网搜索与地图 POI
- TransportAgent 接入地图 MCP
- Main Agent TaskPlan 自动绑定工具
- 无工具时降级内置语料，并记录 fallback

## 11. 验收标准

- 同一个行程：AttractionAgent、FoodAgent、TransportAgent 能并行执行
- Main Agent 能根据意图生成 TaskPlan
- 调整指令只触发局部子 Agent
- 每个子 Agent 的调用和失败可追踪
- AttractionAgent 能通过联网搜索返回经典景点并带来源和坐标
- FoodAgent 能通过联网搜索返回经典美食并带来源
- TransportAgent 能通过地图 MCP 返回交通路线和耗时
- 无 MCP/无网络时自动降级且可追踪
- 多智能体评测通过率不低于 90%
- 人工复核、发布、RBAC、攻略广场功能不回归

## 12. 风险与对策

| 风险 | 对策 |
|---|---|
| 子 Agent 返回不一致 | Synthesis 统一 schema + Validator 兜底 |
| 并行调用成本高 | 按 TaskPlan 控制并行度，可选子任务串行 |
| 局部重规划破坏整体路线 | RouteAgent 接收完整行程上下文做增量修正 |
| 失败定位难 | AgentResult 全量 trace + 子 Agent 指标 |
| 兼容现有前端 | 保持 `/api/chat` 返回结构不变 |

