"""主 Agent：意图识别、参数补全、TaskPlan 生成与调度决策。"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from app.observability.metrics import metrics
from app.services.planner import (
    detect_intent,
    extract_departure_date,
    extract_params,
    mentioned_city,
    normalize_city,
)


class MainAgent:
    def __init__(self, llm: Any = None, searcher: Any = None) -> None:
        self.llm = llm
        self.searcher = searcher

    async def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        text = state.get("user_input", "")
        trip = state.get("existing_trip")
        parsed = await self._llm_parse(text, trip, state.get("history"))
        if parsed:
            text = parsed.get("rewritten_text") or text
            keywords = parsed.get("keywords") or []
            intent = parsed.get("intent")
            params = parsed.get("params")
            changed_fields = parsed.get("changed_fields") or []
        else:
            fallback = self._rules_parse(text, trip)
            text = fallback["rewritten_text"]
            keywords = fallback["keywords"]
            intent = fallback["intent"]
            params = fallback["params"]
            changed_fields = fallback.get("changed_fields") or []
        if intent == "adjust" and not changed_fields:
            changed_fields = self._rule_changed_fields(text)

        if trip:
            merged = dict(trip.get("params") or {})
            explicit = set(params.pop("_explicit_fields", list(params.keys())))
            for key in explicit:
                merged[key] = params[key]
            if not mentioned_city(text):
                merged["city"] = (trip.get("params") or {}).get("city") or merged.get("city", "北京")
            merged["city"] = normalize_city(merged.get("city") or "北京")
            if not merged.get("departure_date"):
                merged["departure_date"] = (date.today() + timedelta(days=1)).isoformat()
            merged["source_text"] = params.get("source_text", "")
            params = merged
        else:
            params.pop("_explicit_fields", None)

        subtasks: list[dict[str, Any]] = []
        if intent == "create":
            subtasks = [
                {"task_id": "attraction", "type": "attraction", "priority": 1, "parallel": True},
                {"task_id": "food", "type": "food", "priority": 1, "parallel": True},
                {"task_id": "transport", "type": "transport", "priority": 1, "parallel": True},
            ]
        elif intent == "adjust":
            subtasks = self._build_adjust_subtasks(text, changed_fields)

        task_plan = {
            "main_intent": intent,
            "params": params,
            "changed_fields": changed_fields if intent == "adjust" else [],
            "subtasks": subtasks,
            "retry_policy": {"max_retries": 2, "retry_agents": ["attraction", "route"]},
        }
        metrics.record_stage("main_plan")
        return {
            "intent": intent,
            "params": params,
            "task_plan": task_plan,
            "existing_plan": (trip or {}).get("itinerary"),
            "history": [{"role": "user", "content": text}],
            "keywords": keywords,
            "rewritten_input": text,
            "session_memory": {
                "last_intent": intent,
                "last_params": params,
                "has_existing_trip": bool(trip),
            },
        }

    async def _llm_parse(
        self,
        text: str,
        trip: dict[str, Any] | None,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        settings = getattr(self.llm, "settings", None)
        if not self.llm or getattr(settings, "llm_mode", "demo") != "openai":
            return None
        system = (
            "你是旅行规划主 Agent。把用户输入改写为清晰可执行的结构化请求，"
            "提取搜索关键词，识别意图并提取行程参数。只输出 JSON，不要 Markdown。"
            "intent 只能是 create/adjust/ask/chat。"
            "如果是调整已有行程，只返回需要修改的字段；用户说“改到/换成/变成某城市”时必须更新 city。"
            '输出格式：{"rewritten_text":"...","keywords":["..."],"intent":"create","params":{"city":"北京","days":3},"changed_fields":[]}'
        )
        existing = json.dumps((trip or {}).get("params") or {}, ensure_ascii=False)
        history_text = ""
        if history:
            recent = history[-8:]
            history_text = "\n".join(
                f"{'用户' if m.get('role') == 'user' else '助手'}：{m.get('content', '')}"
                for m in recent
            )
        user = (
            f"最近对话：\n{history_text}\n\n"
            f"用户消息：{text}\n"
            f"现有行程参数：{existing}"
        )
        try:
            raw = await self.llm.complete(system, user)
            data = self._parse_json(raw)
            if not data:
                return None
            intent = data.get("intent")
            params = data.get("params")
            if intent not in ("create", "adjust", "ask", "chat") or not isinstance(params, dict):
                return None
            rewritten = data.get("rewritten_text") or " ".join(str(text or "").split())
            keywords = data.get("keywords") or self._rule_keywords(text)
            if not trip:
                defaults = extract_params(text)
                merged_params = dict(defaults)
                for key, value in params.items():
                    if value not in (None, ""):
                        merged_params[key] = value
                params = merged_params
                params["city"] = normalize_city(params.get("city") or "")
            params["_explicit_fields"] = [
                key for key in params if key not in ("_explicit_fields", "source_text")
            ]
            return {
                "rewritten_text": rewritten,
                "keywords": keywords,
                "intent": intent,
                "params": params,
                "changed_fields": data.get("changed_fields") or [],
            }
        except Exception:
            return None

    @staticmethod
    def _rule_keywords(text: str) -> list[str]:
        keywords: list[str] = []
        for kw in ("美食", "历史", "文化", "亲子", "自然", "拍照", "轻松", "自驾", "高铁", "公交", "地铁", "打车", "海边", "古镇", "寺庙", "雪山", "夜景"):
            if kw in text:
                keywords.append(kw)
        return keywords

    def _rules_parse(self, text: str, trip: dict[str, Any] | None) -> dict[str, Any]:
        cleaned = " ".join(str(text or "").split())
        return {
            "rewritten_text": cleaned,
            "keywords": self._rule_keywords(cleaned),
            "intent": detect_intent(cleaned, has_trip=bool(trip)),
            "params": extract_params(cleaned),
            "changed_fields": self._rule_changed_fields(cleaned),
        }

    @staticmethod
    def _rule_changed_fields(text: str) -> list[str]:
        fields: list[str] = []
        if mentioned_city(text):
            fields.append("city")
        if extract_departure_date(text) or any(
            k in text for k in ("出发日期", "日期", "提前", "推迟", "改到", "几号")
        ):
            fields.append("date")
        if any(k in text for k in ("预算", "消费", "金额", "钱", "便宜", "贵", "花得")):
            fields.append("budget")
        if any(k in text for k in ("交通", "自驾", "高铁", "公交", "地铁", "打车", "骑行", "共享", "酒店", "附近", "住宿")):
            fields.append("transport")
        if any(k in text for k in ("美食", "火锅", "烤鸭", "小吃", "餐厅", "吃")):
            fields.append("food")
        if any(k in text for k in ("景点", "亲子", "去掉", "删除", "增加", "换", "轻松", "减少", "不想", "不去", "不要", "玩")):
            fields.append("attraction")
        if any(k in text for k in ("一天", "两天", "三天", "四天", "五天", "六天", "七天", "天数", "日游")):
            fields.append("days")
        return list(dict.fromkeys(fields))

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        match = re.search(r"\{[^{}]*\}", text)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return None

    @staticmethod
    def _build_adjust_subtasks(text: str, changed_fields: list[str] | None = None) -> list[dict[str, Any]]:
        changed = changed_fields or []
        if not changed:
            changed = MainAgent._rule_changed_fields(text)
        types: list[str] = []
        if "city" in changed:
            types += ["attraction", "food", "transport"]
        if "days" in changed:
            types += ["attraction", "food"]
        if "budget" in changed or any(
            k in text for k in ("消费太少", "金额太少", "太便宜", "花得太少", "预算没用完")
        ):
            types += ["attraction", "food"]
        if "food" in changed:
            types.append("food")
        if "transport" in changed:
            types.append("transport")
        if "attraction" in changed:
            types.append("attraction")
        if not types:
            return []
        return [
            {
                "task_id": t,
                "type": t,
                "priority": 1,
                "parallel": True,
            }
            for t in dict.fromkeys(types)
        ]

