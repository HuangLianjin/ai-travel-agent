"""主 Agent + 子 Agent 的 LangGraph 图：任务规划 -> Send 并行 -> 路线 -> 校验 -> 综合。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agent.agents import (
    AttractionAgent,
    FoodAgent,
    MainAgent,
    ReflectionAgent,
    RouteAgent,
    SynthesisAgent,
    TransportAgent,
    ValidatorAgent,
)
from app.agent.agents.base import Subtask
from app.agent.state import TravelState
from app.config import get_settings
from app.db import Database
from app.llm import TravelLLM
from app.observability.metrics import metrics
from app.services.planner import apply_reflection_tuning
from app.rag.search import HybridSearcher
from app.tools.content_source import SearchContentSource
from app.tools.external import MapMCPTool, WebSearchTool

_NODE_MAP = {
    "attraction": "specialist_attraction",
    "food": "specialist_food",
    "transport": "specialist_transport",
}


def _fan_out(state: TravelState) -> list[Send]:
    plan = state.get("task_plan", {})
    subtasks = plan.get("subtasks", [])
    sends: list[Send] = []
    for st in subtasks:
        node = _NODE_MAP.get(st.get("type"))
        if node:
            sends.append(Send(node, state))
    return sends or [Send("route_optimize", state)]


def _trip_title(plan: dict[str, Any], params: dict[str, Any]) -> str:
    city = plan.get("city") or params.get("city") or "目的地"
    days = len(plan.get("days", []) or []) or params.get("days") or 1

    def fmt(iso: str) -> str:
        try:
            d = date.fromisoformat(iso)
            return f"{d.month}月{d.day}日"
        except (TypeError, ValueError):
            return ""

    start = params.get("departure_date") or (plan.get("params") or {}).get("departure_date") or ""
    travelers = params.get("travelers", 1) or 1
    if start:
        try:
            end = (date.fromisoformat(start) + timedelta(days=max(1, int(days)) - 1)).isoformat()
            return f"{city} · {days}天{travelers}人\n{fmt(start)}-{fmt(end)}"
        except (TypeError, ValueError):
            pass
    return f"{city}{days}日{travelers}人行程"


def _quality_router(state: TravelState) -> str:
    policy = state.get("task_plan", {}).get("retry_policy", {})
    max_retries = int(policy.get("max_retries", 2) or 0)
    retry_count = int(state.get("retry_count", 0) or 0)
    if not state.get("quality_ok", True) and retry_count < max_retries:
        return "synthesis"
    return "finish"


def _router(state: TravelState) -> str:
    if state.get("intent") in ("ask", "chat"):
        return "finish"
    if state.get("intent") == "adjust":
        changed = (state.get("task_plan") or {}).get("changed_fields") or []
        if changed and all(f in ("date", "departure_date") for f in changed):
            return "synthesis"
    return "dispatch"


def _emit_event(data: dict[str, Any]) -> None:
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(data)
    except Exception:
        pass


def _emit_stage(stage: str, label: str, status: str) -> None:
    _emit_event({"type": "stage", "stage": stage, "label": label, "status": status})


def _emit_days(plan: dict[str, Any]) -> None:
    days = plan.get("days", [])
    for idx, day in enumerate(days, start=1):
        _emit_event({"type": "day", "index": idx, "total": len(days), "day": day})


def _with_stage(stage: str, label: str, fn: Any):
    async def wrapped(state: TravelState) -> dict[str, Any]:
        _emit_stage(stage, label, "start")
        out = await fn(state)
        _emit_stage(stage, label, "done")
        return out

    return wrapped


_AGENT_CACHE: dict[str, Any] = {}


def create_agent(
    db: Database,
    llm: TravelLLM,
    searcher: HybridSearcher | None = None,
    checkpointer: Any = None,
    web_search: Any = None,
    map_mcp: Any = None,
) -> Any:
    settings = get_settings()
    cache_key = (
        f"{getattr(db, '_path', '')}:{settings.llm_mode}:{settings.model_name}:"
        f"{settings.openai_base_url}:{settings.search_provider}:{settings.map_mcp_mode}"
    )
    if cache_key in _AGENT_CACHE:
        return _AGENT_CACHE[cache_key]
    searcher = searcher or HybridSearcher()
    web_search = web_search or WebSearchTool(searcher)
    map_mcp = map_mcp or MapMCPTool(searcher)

    content_source = SearchContentSource(web_search)
    main_agent = MainAgent(llm=llm, searcher=searcher)
    attraction_agent = AttractionAgent(
        searcher=searcher,
        web_search=web_search,
        content_source=content_source,
        map_mcp=map_mcp,
    )
    food_agent = FoodAgent(
        searcher=searcher,
        web_search=web_search,
        content_source=content_source,
        map_mcp=map_mcp,
    )
    transport_agent = TransportAgent(searcher=searcher, map_mcp=map_mcp)
    route_agent = RouteAgent(searcher=searcher, map_mcp=map_mcp)
    validator_agent = ValidatorAgent(searcher=searcher)
    synthesis_agent = SynthesisAgent(
        searcher=searcher, llm=llm, web_search=web_search, map_mcp=map_mcp
    )
    reflection_agent = ReflectionAgent(searcher=searcher, llm=llm)

    async def main_parse(state: TravelState) -> dict[str, Any]:
        trip_id = state.get("trip_id", "")
        trip = db.get_trip(trip_id, state.get("user_id")) if trip_id else None
        planned = await main_agent.plan({**state, "existing_trip": trip})
        if planned.get("intent") in ("ask", "chat"):
            planned["response"] = await llm.complete(
                "你是旅行助手，简短回答用户即可。", state.get("user_input", "")
            )
        return {**planned, "existing_trip": trip}

    async def dispatch(state: TravelState) -> dict[str, Any]:
        params = state.get("params", {})
        query = f"{params.get('city', '')} 景点 美食 {' '.join(params.get('interests', []))}"
        docs = searcher.hybrid_search(query, top_k=15)
        metrics.record_stage("dispatch")
        return {"docs": docs, "agent_results": None}

    def make_specialist(agent: Any, task_type: str):
        async def node(state: TravelState) -> dict[str, Any]:
            subtask = Subtask(
                task_id=task_type,
                type=task_type,
                params=state.get("params", {}),
            )
            result = await agent.run(subtask, state)
            results = list(state.get("agent_results") or [])
            results.append(result.to_dict())
            return {"agent_results": results}

        return node

    async def route_optimize(state: TravelState) -> dict[str, Any]:
        result = await route_agent.run(
            Subtask(task_id="route", type="route", params=state.get("params", {})),
            state,
        )
        results = list(state.get("agent_results") or [])
        results.append(result.to_dict())
        return {"agent_results": results}

    async def validate(state: TravelState) -> dict[str, Any]:
        result = await validator_agent.run(
            Subtask(task_id="validate", type="validate", params=state.get("params", {})),
            state,
        )
        results = list(state.get("agent_results") or [])
        results.append(result.to_dict())
        return {
            "agent_results": results,
            "validation": result.data.get("issues", []),
        }

    async def synthesis(state: TravelState) -> dict[str, Any]:
        feedback = state.get("reflection_feedback") or ""
        if feedback:
            state["user_input"] = (
                f"{state.get('user_input', '')}\n请根据以下问题优化行程：{feedback}"
            )
        result = await synthesis_agent.run(
            Subtask(task_id="synthesis", type="synthesis", params=state.get("params", {})),
            state,
        )
        plan = result.data.get("itinerary", {})
        _emit_days(plan)
        for _ in plan.get("days", []):
            await asyncio.sleep(0.3)
        return {
            "agent_results": [result.to_dict()],
            "itinerary": plan,
            "response": result.data.get("response", ""),
            "version": result.data.get("version", 1),
        }

    async def reflect(state: TravelState) -> dict[str, Any]:
        changed = (state.get("task_plan") or {}).get("changed_fields") or []
        only_date = (
            state.get("intent") == "adjust"
            and changed
            and all(f in ("date", "departure_date") for f in changed)
        )
        if only_date:
            plan = state.get("itinerary") or {}
            return {
                "agent_results": list(state.get("agent_results") or []),
                "itinerary": plan,
                "response": state.get("response", ""),
                "quality_ok": True,
                "retry_count": state.get("retry_count", 0),
                "reflection_feedback": "",
            }
        result = await reflection_agent.run(
            Subtask(task_id="reflect", type="reflect", params=state.get("params", {})),
            state,
        )
        plan = result.data.get("itinerary") or state.get("itinerary") or {}
        plan = apply_reflection_tuning(plan)
        results = list(state.get("agent_results") or [])
        results.append(result.to_dict())
        ok = result.data.get("ok", True)
        feedback = result.data.get("feedback") or ""
        retry_count = state.get("retry_count", 0)
        if not ok:
            retry_count += 1
        return {
            "agent_results": results,
            "itinerary": plan,
            "response": state.get("response", ""),
            "quality_ok": ok,
            "retry_count": retry_count,
            "reflection_feedback": feedback if not ok else "",
        }

    async def finish(state: TravelState) -> dict[str, Any]:
        plan = state.get("itinerary", {})
        response = state.get("response", "")
        trip_id = state.get("trip_id", "")
        if plan and state.get("user_id"):
            params = state.get("params", {})
            if state.get("intent") == "create" and not trip_id:
                trip_id = db.create_trip(
                    state["user_id"],
                    _trip_title(plan, params),
                    plan.get("city", params.get("city", "")),
                    params,
                    plan,
                )
            elif trip_id:
                db.update_trip(
                    trip_id,
                    state.get("version", 1),
                    params,
                    plan,
                    status="draft",
                    title=_trip_title(plan, params),
                    city=plan.get("city") or params.get("city") or None,
                )
        metrics.record_stage("finish")
        return {"response": response, "trip_id": trip_id}

    workflow = StateGraph(TravelState)
    workflow.add_node("main_parse", _with_stage("main_parse", "任务规划", main_parse))
    workflow.add_node("dispatch", _with_stage("dispatch", "并行派发", dispatch))
    workflow.add_node(
        "specialist_attraction",
        _with_stage("attraction", "景点检索", make_specialist(attraction_agent, "attraction")),
    )
    workflow.add_node(
        "specialist_food",
        _with_stage("food", "美食推荐", make_specialist(food_agent, "food")),
    )
    workflow.add_node(
        "specialist_transport",
        _with_stage("transport", "交通规划", make_specialist(transport_agent, "transport")),
    )
    workflow.add_node("route_optimize", _with_stage("route", "路线优化", route_optimize))
    workflow.add_node("validate", _with_stage("validate", "结果校验", validate))
    workflow.add_node("synthesis", _with_stage("synthesis", "综合生成", synthesis))
    workflow.add_node("reflect", _with_stage("reflect", "反思修正", reflect))
    workflow.add_node("finish", _with_stage("finish", "完成", finish))

    workflow.add_edge(START, "main_parse")
    workflow.add_conditional_edges(
        "main_parse",
        _router,
        {"dispatch": "dispatch", "finish": "finish", "synthesis": "synthesis"},
    )
    workflow.add_conditional_edges(
        "dispatch",
        _fan_out,
        ["specialist_attraction", "specialist_food", "specialist_transport"],
    )
    workflow.add_edge("specialist_attraction", "route_optimize")
    workflow.add_edge("specialist_food", "route_optimize")
    workflow.add_edge("specialist_transport", "route_optimize")
    workflow.add_edge("route_optimize", "validate")
    workflow.add_edge("validate", "synthesis")
    workflow.add_edge("synthesis", "reflect")
    workflow.add_conditional_edges(
        "reflect",
        _quality_router,
        {"synthesis": "synthesis", "finish": "finish"},
    )
    workflow.add_edge("finish", END)

    compiled = workflow.compile(checkpointer=checkpointer) if checkpointer else workflow.compile()
    _AGENT_CACHE[cache_key] = compiled
    return compiled

