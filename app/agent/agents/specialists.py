"""景点/美食/交通/路线/校验/综合子 Agent。"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.agents.base import BaseTravelAgent, Subtask
from app.rag.search import HybridSearcher
from app.services.planner import (
    _decorate_plan,
    _diversify_days,
    _enforce_budget,
    _ensure_min_spend,
    _matches_removal,
    _merge_transport_legs,
    _recompute_costs,
    _refresh_timeline,
    apply_adjustment,
    build_itinerary,
    format_reply,
    validate_plan,
)
from app.tools.geo import haversine_km, optimize_route, route_legs

_LISTING_WORDS = (
    "推荐", "攻略", "盘点", "大全", "总结", "必試", "必试", "必尝", "必食",
    "榜单", "排行", "指南", "提到", "附近", "必吃", "必打卡", "哪些", "老味道",
    "百年老", "吃播", "探店", "網紅", "網紅店", "客滿", "鍋氣", "值得体验",
    "值得", "種草", "實測", "實拍", "開箱", "食記", "VLOG", "vlog", "打卡",
    "清单", "私藏", "本地人", "当地人", "宝藏", "隐藏", "小众", "懒人包", "吃喝",
    "玩樂", "餐饮食材", "必去", "10 大", "10大", "十大", "TOP", "top", "前10",
    "老字號", "自由探索", "特色美食", "当地风味", "参考", "随便", "地道", "正宗",
    "这些", "这几家", "几家", "造访", "味道", "价格", "好吃", "好喝", "性价比",
    "人气", "热门", "好评", "网友", "排队", "必点", "招牌", "合集", "测评",
    "实测", "踩雷", "避雷", "拔草", "逛吃", "觅食", "寻味", "吃遍", "吃喝玩乐",
    "一日游", "两日游", "周边游", "旅游攻略", "游玩攻略", "美食地图", "美食攻略",
    "美食推荐", "店名", "店铺", "餐厅推荐", "私房菜", "闽菜", "川菜", "粤菜",
    "种草", "探店报告",
)


def _food_kind(name: str, ptype: str = "") -> str:
    hints = ("小吃", "粉", "汤", "糕", "饼", "糖水", "水煮", "卤", "拌", "煲", "茶", "甜品", "烧烤")
    if any(h in name for h in hints) or "小吃" in str(ptype):
        return "小吃"
    return "餐厅"


def _near_city(
    center: tuple[float, float], lat: Any, lon: Any, max_km: float = 60.0
) -> bool:
    try:
        return (
            haversine_km(float(lat), float(lon), center[0], center[1]) <= max_km
        )
    except (TypeError, ValueError):
        return True


def _is_listing_title(name: str) -> bool:
    if any(k in name for k in _LISTING_WORDS):
        return True
    if re.search(r"\d+\s*家", name):
        return True
    if re.search(r"(这几家|这些|几家|哪些|本地人|当地人|常常|造访|味道正宗|价格良心|连当地)", name):
        return True
    if re.search(r"[-—–~～]\s*(知乎|小红书|马蜂窝|简书|搜狐|百家号|网易|腾讯|公众号|bilibili|哔哩哔哩)", name, re.I):
        return True
    if len(name) > 18 and (name.count("，") >= 2 or name.count(",") >= 2 or name.count("、") >= 2):
        return True
    hints = ("店", "馆", "楼", "庄", "餐厅", "老字号", "老字號", "铺", "坊", "总店", "旗舰店", "门店")
    return len(name) > 12 and not any(h in name for h in hints)


class AttractionAgent(BaseTravelAgent):
    name = "AttractionAgent"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.content_source = kwargs.get("content_source")

    async def _run(self, subtask: Subtask, context: dict[str, Any]) -> dict[str, Any]:
        params = context.get("params", {})
        city = params.get("city", "")
        keywords = context.get("keywords") or []
        interest_text = " ".join(params.get("interests", []))
        if keywords:
            query = f"{city} {' '.join(keywords)} 景点"
        else:
            query = f"{city} 景点 {interest_text}"
        docs = self.searcher.hybrid_search(query, top_k=12)
        attractions = [
            d
            for d in docs
            if d.get("category") == "attraction"
            and (not d.get("city") or d.get("city") == city)
        ]
        if self.web_search:
            try:
                web = await self.web_search.search(query, top_k=3)
            except Exception:
                web = []
            for item in web:
                item["category"] = "attraction"
                if not item.get("city"):
                    item["city"] = city
            attractions.extend(web)
        if self.content_source:
            crawled = await self.content_source.fetch_city(city, "景点")
            attractions.extend(crawled)
        attractions = [
            d for d in attractions if not _is_listing_title(str(d.get("name", "")))
        ]
        if self.map_mcp:
            pois = await self.map_mcp.poi_list(
                f"{city} 景点", city, 20
            )
            known = {a.get("name") for a in attractions if a.get("name")}
            for poi in pois:
                name = poi.get("name", "")
                if not name or name in known:
                    continue
                if any(
                    k in name
                    for k in ("攻略", "推荐", "大全", "旅游攻略", "景点推荐")
                ):
                    continue
                attractions.append(
                    {
                        "id": name,
                        "name": name,
                        "category": "attraction",
                        "city": city,
                        "lat": poi.get("lat", ""),
                        "lon": poi.get("lon", ""),
                        "address": poi.get("address", ""),
                        "duration_hours": 2,
                        "opening_hours": "以景区实际为准",
                        "fee": 0,
                        "tags": ["拍照"],
                        "note": "高德POI真实景点，门票与开放时间以景区公告为准",
                        "source": "高德POI",
                    }
                )
                known.add(name)
        center = await self.map_mcp.geocode_city(city) if self.map_mcp else None
        if center:
            attractions = [
                a
                for a in attractions
                if not (a.get("lat") and a.get("lon"))
                or _near_city(center, a.get("lat"), a.get("lon"))
            ]
        return {"attractions": attractions}


class FoodAgent(BaseTravelAgent):
    name = "FoodAgent"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.content_source = kwargs.get("content_source")

    async def _run(self, subtask: Subtask, context: dict[str, Any]) -> dict[str, Any]:
        params = context.get("params", {})
        city = params.get("city", "")
        keywords = context.get("keywords") or []
        if keywords:
            query = f"{city} {' '.join(keywords)} 特色美食 餐厅 小吃"
        else:
            query = f"{city} 特色美食 最出名 老店 餐厅 地址 总店"
        docs = self.searcher.hybrid_search(query, top_k=8)
        foods = [
            d
            for d in docs
            if d.get("category") == "food"
            and (not d.get("city") or d.get("city") == city)
        ]
        if self.web_search:
            try:
                web = await self.web_search.search(query, top_k=6)
            except Exception:
                web = []
            web = [
                item
                for item in web
                if not _is_listing_title(str(item.get("name", "")))
            ]
            restaurant_hints = ("店", "馆", "楼", "庄", "餐厅", "老字号", "老字號", "铺", "坊", "总店", "创始", "最出名", "名店")
            web.sort(
                key=lambda item: 0
                if any(h in str(item.get("name", "")) for h in restaurant_hints)
                else 1
            )
            for item in web:
                item["category"] = "food"
                if not item.get("city"):
                    item["city"] = city
            foods.extend(web)
        if self.content_source:
            crawled = await self.content_source.fetch_city(city, "美食")
            foods.extend(crawled)
        foods = [
            d for d in foods if not _is_listing_title(str(d.get("name", "")))
        ]
        if self.map_mcp:
            for item in foods[:4]:
                if not item.get("address"):
                    poi = await self.map_mcp.poi_detail(
                        f"{city} {item.get('name', '')}", city
                    )
                    if poi:
                        item["address"] = poi.get("address", "")
                        item["lat"] = poi.get("lat") or item.get("lat")
                        item["lon"] = poi.get("lon") or item.get("lon")
                        item["restaurant"] = poi.get("name") or item.get("restaurant") or ""
                        item["review_score"] = poi.get("rating") or item.get("review_score") or ""
                        item["food_type"] = _food_kind(
                            item.get("name", ""), poi.get("type", "")
                        )
                        if poi.get("cost"):
                            try:
                                item["price"] = int(float(poi["cost"]))
                                item["price_source"] = "高德参考价"
                            except (TypeError, ValueError):
                                pass
            if len(foods) < 15:
                pois = await self.map_mcp.poi_list(
                    f"{city} 特色美食", city, 20
                )
                if len(foods) < 15:
                    pois.extend(
                        await self.map_mcp.poi_list(
                            f"{city} 小吃", city, 15 - len(foods)
                        )
                    )
                if len(foods) < 15:
                    pois.extend(
                        await self.map_mcp.poi_list(
                            f"{city} 特色小吃", city, 15 - len(foods)
                        )
                    )
                if len(foods) < 15:
                    pois.extend(
                        await self.map_mcp.poi_list(
                            f"{city} 名小吃", city, 15 - len(foods)
                        )
                    )
                if len(foods) < 15:
                    pois.extend(
                        await self.map_mcp.poi_list(
                            f"{city} 餐厅", city, 15 - len(foods)
                        )
                    )
                pois = [
                    p
                    for p in pois
                    if not any(
                        k in p.get("name", "")
                        for k in ("美食街", "美食广场", "美食城", "攻略", "推荐")
                    )
                ]
                known = {f.get("name") for f in foods if f.get("name")}
                for poi in pois:
                    name = poi.get("name", "")
                    if not name or name in known:
                        continue
                    cost = poi.get("cost")
                    try:
                        cost_value = int(float(cost)) if cost else None
                    except (TypeError, ValueError):
                        cost_value = None
                    foods.append(
                        {
                            "id": name,
                            "name": name,
                            "restaurant": name,
                            "category": "food",
                            "city": city,
                            "address": poi.get("address", ""),
                            "lat": poi.get("lat", ""),
                            "lon": poi.get("lon", ""),
                            "price": cost_value,
                            "price_source": "高德参考价" if cost_value else "",
                            "review_score": poi.get("rating", ""),
                            "food_type": _food_kind(name, poi.get("type", "")),
                            "note": "高德POI真实餐饮，人均消费来自高德",
                            "source": "高德POI",
                        }
                    )
                    known.add(name)
                    if len(foods) >= 15:
                        break
        restaurants = [f for f in foods if f.get("food_type") != "小吃"]
        snacks = [f for f in foods if f.get("food_type") == "小吃"]
        interleaved = []
        ri = si = 0
        while ri < len(restaurants) or si < len(snacks):
            if ri < len(restaurants):
                interleaved.append(restaurants[ri])
                ri += 1
            if si < len(snacks):
                interleaved.append(snacks[si])
                si += 1
        foods = interleaved
        center = await self.map_mcp.geocode_city(city) if self.map_mcp else None
        if center:
            foods = [
                f
                for f in foods
                if not (f.get("lat") and f.get("lon"))
                or _near_city(center, f.get("lat"), f.get("lon"))
            ]
        return {"foods": foods}


class TransportAgent(BaseTravelAgent):
    name = "TransportAgent"

    async def _run(self, subtask: Subtask, context: dict[str, Any]) -> dict[str, Any]:
        params = context.get("params", {})
        docs = context.get("docs", []) or []
        hubs = [d for d in docs if d.get("category") == "transport"]
        attractions = [d for d in docs if d.get("category") == "attraction"]
        legs = []
        if self.map_mcp and attractions:
            legs = await self.map_mcp.distance_matrix(
                attractions[:3], preference=params.get("transport", "auto")
            )
        return {
            "transport_hub": hubs[0] if hubs else None,
            "mode": params.get("transport", "地铁/公交"),
            "legs": legs,
        }


class RouteAgent(BaseTravelAgent):
    name = "RouteAgent"

    async def _run(self, subtask: Subtask, context: dict[str, Any]) -> dict[str, Any]:
        docs = context.get("docs", []) or []
        attractions = [d for d in docs if d.get("category") == "attraction"]
        ordered = optimize_route(attractions)
        return {"ordered_attractions": ordered, "legs": route_legs(ordered)}


class ValidatorAgent(BaseTravelAgent):
    name = "ValidatorAgent"

    async def _run(self, subtask: Subtask, context: dict[str, Any]) -> dict[str, Any]:
        plan = context.get("itinerary") or {}
        if not plan:
            return {"valid": True, "issues": []}
        plan = validate_plan(plan)
        return {
            "valid": plan.get("valid", True),
            "issues": plan.get("validation_issues", []),
        }


class ReflectionAgent(BaseTravelAgent):
    """生成后反思：规则 + 可选 LLM 双重审查，输出可执行改进建议。"""

    name = "ReflectionAgent"

    async def _run(self, subtask: Subtask, context: dict[str, Any]) -> dict[str, Any]:
        plan = context.get("itinerary") or {}
        issues = list(context.get("validation") or [])
        issues.extend(list(plan.get("validation_issues") or []))
        notes: list[str] = []

        budget = plan.get("budget") or {}
        if budget.get("within_budget") is False:
            notes.append("当前估算超出预算，建议删减高消费项目或调整预算")

        hot_spots = ("故宫", "长城", "迪士尼", "大熊猫", "环球影城", "颐和园", "天安门")
        for day in plan.get("days", []):
            total = sum(leg.get("minutes", 0) for leg in day.get("route", []))
            if total > 180:
                notes.append(
                    f"Day {day.get('day')} 移动时间较长（约 {total} 分钟），建议精简一个景点"
                )
            names = [a.get("name", "") for a in day.get("attractions", [])]
            hit = next((k for k in hot_spots if any(k in n for n in names)), None)
            if hit:
                notes.append(
                    f"Day {day.get('day')} 的 {hit} 属于热门景点，建议提前 1-7 天官方预约购票"
                )

        for item in plan.get("weather", []) or []:
            if "雨" in str(item.get("text", "")):
                notes.append(f"{item.get('date')} 有降雨，建议带伞并预留弹性时间")
        for item in plan.get("weather_warnings", []) or []:
            notes.append(f"天气预警：{item.get('title')}")

        if not plan.get("sources"):
            issues.append("缺少来源约束，禁止发布无来源内容")

        unique: list[str] = []
        for note in notes:
            if note not in unique:
                unique.append(note)
        notes = unique

        mode = "rules"

        ok = True
        feedback: list[str] = []
        for day in plan.get("days", []) or []:
            if not day.get("attractions") or not day.get("dining"):
                ok = False
                feedback.append(f"Day {day.get('day')} 缺少景点或美食")
            tl = day.get("timeline") or []
            if tl:
                try:
                    hour = int(str(tl[-1].get("time", "")).split(":")[0])
                    if hour > 22:
                        ok = False
                        feedback.append(f"Day {day.get('day')} 结束时间超过 22 点")
                except (TypeError, ValueError):
                    pass
        plan["reflection_notes"] = notes
        plan["validation_issues"] = sorted(set(issues))
        plan["valid"] = not plan["validation_issues"]
        return {
            "itinerary": plan,
            "notes": notes,
            "mode": mode,
            "ok": ok,
            "feedback": "；".join(feedback or notes[:2]),
        }

class SynthesisAgent(BaseTravelAgent):
    name = "SynthesisAgent"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.llm = kwargs.get("llm")

    async def _run(self, subtask: Subtask, context: dict[str, Any]) -> dict[str, Any]:
        params = context.get("params", {})
        results = context.get("agent_results", []) or []
        raw_docs = self._collect_subagent_docs(results, context.get("docs", []) or [])
        docs = self._rule_clean_docs(raw_docs, params)
        transport = self._collect_transport(results)
        existing = context.get("existing_plan") or context.get("itinerary") or {}

        task_plan = context.get("task_plan") or {}
        changed_fields = task_plan.get("changed_fields") or []
        only_date_change = (
            context.get("intent") == "adjust"
            and bool(existing)
            and bool(changed_fields)
            and all(f in ("date", "departure_date") for f in changed_fields)
        )

        if only_date_change:
            import copy

            plan = copy.deepcopy(existing)
            merged_params = dict(existing.get("params") or {})
            merged_params.update(params)
            plan["params"] = merged_params
            plan["city"] = (
                existing.get("city")
                or params.get("city")
                or plan.get("city")
                or "北京"
            )
            plan = _recompute_costs(plan)
            plan = self._refresh_summary(plan, merged_params)
            version = int(context.get("version", 1)) + 1
            mode = "date_only"
            response = (
                f"已更新出发日期为 {params.get('departure_date')}，"
                "行程内容保持不变。"
            )
        else:
            plan = None
            mode = "rules"
            try:
                plan = await self._llm_build_plan(
                    params,
                    docs,
                    existing,
                    context.get("user_input", ""),
                    transport,
                )
                if plan:
                    mode = "llm"
            except Exception:
                plan = None

            if existing:
                base_plan = plan or existing
                plan = apply_adjustment(
                    base_plan,
                    context.get("user_input", ""),
                    docs,
                    params,
                )
                version = int(context.get("version", 1)) + 1
            elif not plan:
                plan = build_itinerary(params, raw_docs or docs, self.searcher or HybridSearcher())
                version = 1
            else:
                version = 1

            plan = self._correct_plan(plan, docs)
            plan = await self._clean_listing_names(plan, docs)
            plan = self._optimize_plan(plan, docs)
            plan = validate_plan(plan)
            plan = await self._enrich_transport_legs(plan)
            if transport:
                plan["transport"] = transport
                plan = _merge_transport_legs(plan)
                plan = _refresh_timeline(plan)
                plan = _recompute_costs(plan)
                plan = _enforce_budget(plan)

            if any(
                k in context.get("user_input", "")
                for k in ("去掉", "不要", "不想", "不去", "删除", "删")
            ):
                plan = self._enforce_removals(plan, context.get("user_input", ""))
            plan = self._refresh_summary(plan, params)
            response = format_reply(plan, context.get("intent", "create"))
        departure_date = params.get("departure_date") or ""
        for key in (
            "weather",
            "weather_advice",
            "weather_warnings",
            "weather_unavailable",
            "weather_notice",
            "weather_max_days",
            "weather_missing",
        ):
            plan.pop(key, None)
        if departure_date:
            from app.tools.weather import (
                WeatherService,
                travel_advice,
                weather_unavailable_notice,
            )

            city = plan.get("city") or params.get("city") or "北京"
            plan["city"] = city
            first_attr = None
            for day in plan.get("days", []):
                if day.get("attractions"):
                    first_attr = day["attractions"][0]
                    break
            lat = first_attr.get("lat") if first_attr else None
            lon = first_attr.get("lon") if first_attr else None
            days = len(plan.get("days", []) or []) or 1
            weather_service = WeatherService()
            max_days = weather_service.max_forecast_days()
            plan["weather_max_days"] = max_days
            weather = await weather_service.forecast(
                city, lat, lon, departure_date, days
            )
            missing: list[dict[str, Any]] = []
            try:
                from datetime import date, timedelta as _timedelta
                start = date.fromisoformat(departure_date)
                for i in range(max(1, int(days))):
                    day_iso = (start + _timedelta(days=i)).isoformat()
                    if not any(str(w.get("date", "")) == day_iso for w in weather):
                        missing.append(
                            {
                                "date": day_iso,
                                "reason": weather_unavailable_notice(
                                    day_iso, max_days
                                ),
                            }
                        )
            except (TypeError, ValueError):
                missing = []
            if missing:
                plan["weather_missing"] = missing
            else:
                plan.pop("weather_missing", None)
            if weather:
                plan["weather"] = weather
                plan["weather_advice"] = travel_advice(weather)
                labels = "；".join(
                    f"{w['date']} {w['text']} {w['temp_min']}~{w['temp_max']}℃"
                    for w in weather[:7]
                )
                response += f"\n\n出发日期 {departure_date} 天气预报：{labels}\n{plan['weather_advice']}"
                warnings = await weather_service.warnings(city, lat, lon)
                if warnings:
                    plan["weather_warnings"] = warnings
                    response += "\n天气预警：" + "；".join(
                        f"{w['title']}：{w['text']}" for w in warnings
                    )
                plan = _refresh_timeline(plan)
                if missing:
                    response += "\n\n天气说明：" + "；".join(
                        m["reason"] for m in missing[:5]
                    )
            else:
                plan["weather_unavailable"] = True
                plan["weather_notice"] = weather_unavailable_notice(
                    departure_date, weather_service.max_forecast_days()
                )
                response += f"\n\n出发日期 {departure_date}：{plan['weather_notice']}"
        else:
            plan["weather_unavailable"] = True
            plan["weather_notice"] = "尚未设置出发日期，无法查询当天天气。"
            response += "\n\n请告诉我你计划哪天出发（例如 2026-08-25），我会帮你查那几天天气并给出出行建议。"

        from app.tools.live_data import LiveDataService

        plan = await LiveDataService().enrich_plan(plan, departure_date)
        if not plan.get("hotel_options"):
            plan["hotel_options"] = await self._search_hotel_options(plan)
        hotel_options = plan.get("hotel_options") or []
        if hotel_options:
            labels = []
            for h in hotel_options[:3]:
                price_txt = f"¥{h.get('price')}/晚" if h.get("price") else "价格待询"
                labels.append(
                    f"{h.get('name')}（{h.get('room_type') or '大床房'} · {price_txt}）"
                )
            response += (
                "\n\n住宿建议：" + "；".join(labels) + "。"
            )

        for day in plan.get("days", []) or []:
            day.pop("llm_timeline", None)

        return {
            "itinerary": plan,
            "response": response,
            "version": version,
            "synthesis_mode": mode,
            "agents_used": sorted(
                {
                    r.get("agent", "")
                    for r in results
                    if r.get("status") == "success"
                }
            ),
        }

    async def _enrich_transport_legs(
        self, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """按当天实际顺序补齐高德交通，覆盖景点和美食之间的全部路段。"""
        if not self.map_mcp:
            return plan
        params = plan.get("params") or {}
        preference = params.get("transport", "auto")
        city = plan.get("city") or params.get("city") or ""
        for day in plan.get("days", []) or []:
            attractions = day.get("attractions", []) or []
            dining = day.get("dining", []) or []
            order: list[tuple[str, dict[str, Any]]] = []
            lunch = dining[0] if dining else None
            snack = dining[1] if len(dining) >= 2 else None
            dinner = dining[2] if len(dining) >= 3 else None
            extras = dining[3:]
            if attractions:
                order.append(("attraction", attractions[0]))
            if lunch:
                order.append(("food", lunch))
            if len(attractions) >= 2:
                order.append(("attraction", attractions[1]))
            if snack:
                order.append(("food", snack))
            if len(attractions) >= 3:
                order.append(("attraction", attractions[2]))
            if dinner:
                order.append(("food", dinner))
            for f in extras:
                order.append(("food", f))

            for kind, item in order:
                if item.get("lat") and item.get("lon"):
                    continue
                if kind == "food" and self.map_mcp:
                    try:
                        poi = await self.map_mcp.poi_detail(
                            f"{city} {item.get('name', '')}", city
                        )
                    except Exception:
                        poi = None
                    if poi:
                        item["lat"] = poi.get("lat") or item.get("lat")
                        item["lon"] = poi.get("lon") or item.get("lon")
                        item["address"] = poi.get("address") or item.get("address")

            legs: list[dict[str, Any]] = []
            for i in range(len(order) - 1):
                _, origin = order[i]
                _, destination = order[i + 1]
                if not (origin.get("lat") and origin.get("lon")) or not (
                    destination.get("lat") and destination.get("lon")
                ):
                    continue
                try:
                    leg = await self.map_mcp.smart_route(
                        {
                            "name": origin.get("name", ""),
                            "lat": origin.get("lat"),
                            "lon": origin.get("lon"),
                            "city": city,
                        },
                        {
                            "name": destination.get("name", ""),
                            "lat": destination.get("lat"),
                            "lon": destination.get("lon"),
                            "city": city,
                        },
                        preference,
                    )
                except Exception:
                    leg = {}
                if leg:
                    legs.append(
                        {
                            "from": origin.get("name", ""),
                            "to": destination.get("name", ""),
                            **leg,
                        }
                    )
            if legs:
                day["route"] = legs
        return plan

    async def _clean_listing_names(
        self, plan: dict[str, Any], docs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """规则过滤后仍存在的可疑标题，交给大模型提取真实店名。"""
        if not self.llm:
            return plan
        settings = getattr(self.llm, "settings", None)
        if not settings or getattr(settings, "llm_mode", "demo") != "openai":
            return plan

        suspects: list[str] = []
        for day in plan.get("days", []) or []:
            for f in day.get("dining", []) or []:
                name = str(f.get("name", ""))
                if name and _is_listing_title(name):
                    suspects.append(name)
        if not suspects:
            return plan

        lines: list[str] = []
        seen: set[str] = set()
        for name in suspects[:8]:
            if name in seen:
                continue
            seen.add(name)
            doc = next((d for d in docs if str(d.get("name", "")) == name), {})
            context = str(doc.get("content") or doc.get("note") or "")[:400]
            lines.append(
                json.dumps(
                    {"original": name, "context": context},
                    ensure_ascii=False,
                )
            )

        system = (
            "你是美食数据清洗器。用户会给你一批可能混入攻略标题的美食候选。"
            "请从 original 或 context 中提取真实店铺名称，只保留明确店名。"
            '只输出 JSON 数组，例如 [{"original":"...","store_name":"同利肉燕老铺"}]。'
            "如果 original 本身就是真实店名，store_name 原样返回；"
            "如果无法提取，store_name 返回空字符串。"
        )
        user = "\n".join(lines)
        try:
            raw = await self.llm.complete(system, user)
            data = self._parse_json(raw)
            mapping: dict[str, str] = {}
            items = data if isinstance(data, list) else (
                data.get("items") if isinstance(data, dict) else []
            )
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    original = str(item.get("original") or "")
                    store = str(item.get("store_name") or "").strip()
                    if original and store and not _is_listing_title(store):
                        mapping[original] = store
            if not mapping:
                return plan
            for day in plan.get("days", []) or []:
                for f in day.get("dining", []) or []:
                    name = str(f.get("name", ""))
                    if name in mapping:
                        f["name"] = mapping[name]
                        f["note"] = (f.get("note") or "") + "（已从攻略标题提取真实店名）"
                        f["name_cleaned"] = True
            return plan
        except Exception:
            return plan

    @staticmethod
    def _extract_hotel_name(raw: str) -> str | None:
        """从搜索结果中提取具体酒店名，拒绝文章/榜单类标题。"""
        raw = (raw or "").strip()
        if not raw:
            return None
        markers = ("酒店", "宾馆", "饭店", "民宿", "公寓", "客栈", "旅馆", "度假村", "山庄")
        dirty = (
            "怎么选", "谁更", "拆解", "维度", "FAQ", "攻略", "大全", "榜单",
            "精选", "盘点", "预订", "优惠", "价格", "一晚", "推荐", "附近",
            "住宿", "新闻", "百家号", "搜狐", "新浪", "网易", "知乎",
        )
        article_hints = (
            "怎么选", "谁更", "拆解", "维度", "FAQ", "攻略", "榜单",
            "精选", "盘点", "预订", "一晚", "推荐",
        )
        candidates: list[tuple[str, bool]] = []
        for segment in re.split(r"[|_—\-]+", raw):
            segment = segment.strip()
            if not segment:
                continue
            m = re.search(
                r"([\u4e00-\u9fa5A-Za-z0-9·]{2,40}(?:酒店|宾馆|饭店|民宿|公寓|客栈|旅馆|度假村|山庄)(?:\([^)]{0,30}\))?)",
                segment,
            )
            if m:
                candidate = m.group(1)
                trusted = segment == candidate or segment.strip() == candidate
                if not trusted and any(h in segment for h in article_hints):
                    trusted = False
                candidates.append((candidate, trusted))
            elif len(segment) <= 30 and any(k in segment for k in markers):
                candidates.append((segment, True))
        for candidate, trusted in reversed(candidates):
            candidate = candidate.strip(" ··|-—")
            if not (2 <= len(candidate) <= 40):
                continue
            if not trusted:
                continue
            if any(k in candidate for k in dirty):
                continue
            return candidate
        return None

    async def _search_hotel_options(
        self, plan: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not self.web_search:
            return []
        city = plan.get("city", "")
        try:
            results = await self.web_search.search(
                f"{city} 酒店 推荐 价格 一晚", top_k=4
            )
        except Exception:
            results = []
        hotels = []
        for item in results:
            name = self._extract_hotel_name(
                item.get("name") or item.get("title") or ""
            )
            if not name:
                continue
            if any(
                k in name
                for k in ("预订", "優惠", "优惠", "热门", "大全", "排行", "精选", "$", "HK")
            ):
                continue
            content = f"{name} {item.get('content', '')}"
            m = re.search(r"¥\s*(\d{2,4})", content) or re.search(
                r"(\d{2,4})\s*元", content
            )
            if "大床房" in content:
                room_type = "大床房"
            elif "双床房" in content or "双人床" in content:
                room_type = "双床房"
            else:
                room_type = ""
            hotels.append(
                {
                    "name": name,
                    "stars": "",
                    "review_score": "",
                    "price": int(m.group(1)) if m else None,
                    "currency": "CNY",
                    "distance_km": "",
                    "lat": "",
                    "lon": "",
                    "url": item.get("url") or "",
                    "source": "SerpAPI 搜索推荐",
                    "room_type": room_type,
                }
            )
            if len(hotels) >= 3:
                break
        if len(hotels) < 3 and self.map_mcp:
            try:
                pois = await self.map_mcp.poi_list(
                    f"{city} 酒店", city, 3 - len(hotels)
                )
            except Exception:
                pois = []
            for poi in pois:
                if any(h.get("name") == poi.get("name") for h in hotels):
                    continue
                hotels.append(
                    {
                        "name": poi.get("name", ""),
                        "stars": "",
                        "review_score": "",
                        "price": None,
                        "currency": "CNY",
                        "distance_km": "",
                        "lat": poi.get("lat", ""),
                        "lon": poi.get("lon", ""),
                        "address": poi.get("address", ""),
                        "url": "",
                        "source": "高德POI真实酒店",
                        "room_type": "",
                    }
                )
                if len(hotels) >= 3:
                    break
        if not hotels:
            return []
        if hotels:
            for i, h in enumerate(hotels):
                h.setdefault("room_type", "大床房" if i == 0 else "双床房")
            plan["hotel_options"] = hotels
        return hotels

    async def _llm_build_plan(
        self,
        params: dict[str, Any],
        docs: list[dict[str, Any]],
        existing: dict[str, Any],
        instruction: str,
        transport: dict[str, Any],
    ) -> dict[str, Any] | None:
        settings = getattr(self.llm, "settings", None)
        if not self.llm or getattr(settings, "llm_mode", "demo") != "openai":
            return None

        doc_lines = []
        for doc in docs[:25]:
            doc_lines.append(
                "- " + " | ".join(
                    str(doc.get(k, "")) for k in ("name", "city", "source", "note")
                )
            )
        system = (
            "你是资深旅行规划师。根据用户参数和检索结果，输出严格 JSON 行程，"
            "不要输出 Markdown。字段必须包含 summary、days、sources；"
            "days 内每项包含 day、theme、attractions、dining、route、timeline。"
            "只能从检索结果中选择真实存在的景点和餐厅，禁止自创名称或写占位词。"
            "检索结果只是攻略参考，不要全部写入行程，要按当地特色、路线合理性和游玩节奏整理优化。"
            "每天安排要充实，景点 3-4 个、餐饮 3 家左右（可以略有多有少），"
            "餐厅、小吃、街边小店、老店混排。"
            "每个景点游玩时间按实际 2-3 小时安排，节奏舒缓不要赶场，不同景点时长自然差异化。"
            "timeline 是当天完整活动时间线，由你根据检索资料和真实作息决定，不要套固定模板。每项包含 time（HH:MM）、type（attraction/food/rest）、title、duration_minutes、可选 note；title 必须来自当天 attractions/dining 或真实检索结果。吃饭要放在正常饭点，例如午餐 11:30-13:00、晚餐 17:30-19:30；不要在景点后立刻安排下一顿正餐，两顿正餐之间至少间隔 3-4 小时，可穿插小吃或自由活动。每天从 09:00 前后自然开始，结束控制在 20:00-21:30，不超过 22:00。"
            "dining 是当天美食推荐列表，不要按早餐/午餐/晚餐划分，"
            "不要输出 meal_type 或 meal 字段；每项必须包含 name 和 price。dining.name 必须是具体店铺或特色小吃的真实名称，禁止使用'本地人私藏''美食清单''必吃榜''X家餐厅''探店/吃播标题'这类攻略标题。"
        )
        user = (
            f"参数：{json.dumps(params, ensure_ascii=False)}\n"
            f"现有行程：{json.dumps(existing, ensure_ascii=False)[:2000]}\n"
            f"用户调整：{instruction}\n"
            f"交通：{json.dumps(transport, ensure_ascii=False)[:500]}\n"
            f"检索结果：\n{'\n'.join(doc_lines)}"
        )
        raw = await self.llm.complete(system, user)
        data = self._parse_json(raw)
        if not data or not isinstance(data.get("days"), list):
            return None
        for day in data.get("days", []) or []:
            tl = self._normalize_llm_timeline(day.get("timeline") or [])
            if tl:
                day["llm_timeline"] = tl
            self._normalize_plan_day(day, docs)
        city = params.get("city", "")
        plan = {
            "city": city,
            "summary": data.get("summary") or f"{city} {params.get('days', 2)} 日行程",
            "params": params,
            "days": data["days"],
            "transport_hub": transport.get("transport_hub"),
            "budget": {},
            "sources": data.get("sources") or sorted(
                {d.get("source", "") for d in docs if d.get("source")}
            ),
        }
        plan = _ensure_min_spend(plan, docs, params)
        return _enforce_budget(plan)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            data = json.loads(text)
            if isinstance(data, (dict, list)):
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
    def _normalize_plan_day(day: dict[str, Any], docs: list[dict[str, Any]]) -> dict[str, Any]:
        by_name = {d.get("name", ""): d for d in docs if d.get("name")}
        for key in ("attractions", "dining"):
            items = day.get(key) or []
            normalized = []
            for item in items:
                if isinstance(item, str):
                    doc = by_name.get(item)
                    normalized.append(doc or {"name": item})
                elif isinstance(item, dict):
                    normalized.append(item)
            day[key] = normalized
        route = day.get("route") or []
        day["route"] = [r for r in route if isinstance(r, dict)]
        return day

    @staticmethod
    def _rule_clean_docs(
        docs: list[dict[str, Any]], params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        chosen: list[dict[str, Any]] = []
        seen: set[str] = set()
        for d in docs or []:
            name = str(d.get("name", "")).strip()
            key = str(d.get("id") or name)
            if not name or key in seen:
                continue
            if _is_listing_title(name):
                continue
            seen.add(key)
            chosen.append(d)
        days = max(1, int(params.get("days", 2) or 2))
        attr_total = len([d for d in chosen if d.get("category") == "attraction"])
        food_total = len([d for d in chosen if d.get("category") == "food"])
        min_attr = min(attr_total, days * 3)
        min_food = min(food_total, days * 3)
        for d in docs or []:
            key = str(d.get("id") or d.get("name") or "")
            if key in seen:
                continue
            attr_count = sum(1 for c in chosen if c.get("category") == "attraction")
            food_count = sum(1 for c in chosen if c.get("category") == "food")
            if d.get("category") == "attraction" and attr_count < min_attr:
                chosen.append(d)
                seen.add(key)
            elif d.get("category") == "food" and food_count < min_food:
                chosen.append(d)
                seen.add(key)
        return chosen

    @staticmethod
    def _refresh_summary(plan: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as _date

        city = plan.get("city") or params.get("city") or ""
        days = len(plan.get("days") or []) or params.get("days") or 1
        travelers = params.get("travelers", 1) or 1
        dep = params.get("departure_date") or ""
        budget = params.get("budget")
        parts = [f"{city}{days}天{travelers}人"]
        if dep:
            try:
                d = _date.fromisoformat(dep)
                parts.append(f"{d.month}月{d.day}日出发")
            except (TypeError, ValueError):
                parts.append(f"{dep}出发")
        if budget:
            parts.append(f"预算{budget}元")
        plan["summary"] = "，".join(parts) + "。"
        return plan

    @staticmethod
    def _enforce_removals(plan: dict[str, Any], instruction: str) -> dict[str, Any]:
        """用户明确说去掉/不要时，最终结果里强制删除，避免后续步骤加回。"""
        for day in plan.get("days", []) or []:
            day["attractions"] = [
                a
                for a in day.get("attractions", []) or []
                if not _matches_removal(str(a.get("name", "")), instruction)
            ]
            day["dining"] = [
                f
                for f in day.get("dining", []) or []
                if not _matches_removal(str(f.get("name", "")), instruction)
            ]
            kept_tl = []
            for item in day.get("timeline", []) or []:
                nm = item.get("title") or item.get("restaurant") or item.get("name") or ""
                if not _matches_removal(str(nm), instruction):
                    kept_tl.append(item)
            day["timeline"] = kept_tl
        plan = _refresh_timeline(plan)
        return _recompute_costs(plan)

    @staticmethod
    def _find_replacement(
        docs: list[dict[str, Any]], category: str, used: set[str]
    ) -> dict[str, Any] | None:
        for d in docs or []:
            name = str(d.get("name", "")).strip()
            if d.get("category") != category or not name:
                continue
            if name in used or _is_listing_title(name):
                continue
            return d
        return None

    @staticmethod
    def _optimize_plan(plan: dict[str, Any], docs: list[dict[str, Any]]) -> dict[str, Any]:
        used_foods: set[str] = set()
        used_attrs: set[str] = set()
        changed = False
        for day in plan.get("days", []) or []:
            dining = day.get("dining") or []
            new_dining = []
            for f in dining:
                name = str(f.get("name", "")).strip()
                if name and name in used_foods:
                    replacement = SynthesisAgent._find_replacement(docs, "food", used_foods)
                    if replacement:
                        f = dict(replacement)
                        f["price"] = replacement.get("price") or replacement.get("fee") or 0
                        changed = True
                if f.get("name"):
                    used_foods.add(str(f.get("name")))
                    new_dining.append(f)
            day["dining"] = new_dining

            attractions = day.get("attractions") or []
            new_attrs = []
            for a in attractions:
                name = str(a.get("name", "")).strip()
                if name and name in used_attrs:
                    replacement = SynthesisAgent._find_replacement(docs, "attraction", used_attrs)
                    if replacement:
                        a = dict(replacement)
                        changed = True
                if a.get("name"):
                    used_attrs.add(str(a.get("name")))
                    new_attrs.append(a)
            day["attractions"] = new_attrs
        plan = _enforce_budget(plan)
        plan = _refresh_timeline(plan)
        plan = _recompute_costs(plan)
        return plan

    @staticmethod
    def _normalize_llm_timeline(raw_timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in raw_timeline or []:
            if not isinstance(item, dict):
                continue
            t = (
                item.get("time")
                or item.get("start_time")
                or item.get("start")
                or item.get("time_start")
                or ""
            )
            if not isinstance(t, str):
                continue
            t = t.strip().split("-")[0].split("~")[0].strip()
            if ":" not in t:
                continue
            try:
                hh, mm = t.split(":")
                time_minutes = int(hh) * 60 + int(mm)
                if not (0 <= time_minutes < 1440):
                    continue
            except (TypeError, ValueError):
                continue
            kind = str(item.get("type") or "").lower()
            if kind in (
                "restaurant", "dining", "food", "meal", "eat", "美食",
                "午餐", "晚餐", "早餐", "吃饭", "用餐", "小吃", "下午茶", "茶歇",
                "brunch", "lunch", "dinner", "breakfast",
            ):
                kind = "food"
            elif kind in (
                "attraction", "spot", "sightseeing", "visit", "play", "景点",
                "游览", "游玩", "参观", "观光",
            ):
                kind = "attraction"
            elif kind in (
                "rest", "break", "free", "休息", "自由活动", "自由", "闲逛", "散步", "coffee",
            ):
                kind = "rest"
            elif kind in ("transport", "traffic", "交通", "前往", "transfer"):
                continue
            elif kind in ("hotel", "hotel_return", "回酒店", "酒店"):
                continue
            else:
                continue
            title = str(item.get("title") or item.get("name") or item.get("place") or "").strip()
            if not title:
                continue
            duration = 0
            for key in ("duration_minutes", "minutes", "duration", "spend_minutes"):
                try:
                    duration = int(item.get(key) or 0)
                    break
                except (TypeError, ValueError):
                    continue
            if not duration:
                duration = 55 if kind == "food" else (120 if kind == "attraction" else 30)
            out.append(
                {
                    "time": f"{int(hh):02d}:{int(mm):02d}",
                    "time_minutes": time_minutes,
                    "type": kind,
                    "title": title,
                    "duration_minutes": max(20, min(int(duration), 240)),
                    "note": str(item.get("note") or ""),
                }
            )
        out.sort(key=lambda x: x["time_minutes"])
        return out

    @staticmethod
    def _collect_subagent_docs(
        results: list[dict[str, Any]], fallback_docs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        for result in results:
            data = result.get("data") or {}
            if result.get("agent") == "AttractionAgent":
                docs.extend(data.get("attractions") or [])
            elif result.get("agent") == "FoodAgent":
                docs.extend(data.get("foods") or [])
        if not docs:
            docs = list(fallback_docs)
        unique: dict[str, dict[str, Any]] = {}
        for doc in docs:
            key = doc.get("id") or doc.get("name") or ""
            if key and key not in unique:
                unique[key] = doc
        return list(unique.values())

    @staticmethod
    def _collect_transport(results: list[dict[str, Any]]) -> dict[str, Any]:
        for result in results:
            if result.get("agent") == "TransportAgent":
                return result.get("data") or {}
        return {}

    @staticmethod
    def _correct_plan(
        plan: dict[str, Any], docs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        from app.corpus import build_docs

        corpus_docs = build_docs()
        by_name: dict[str, dict[str, Any]] = {
            d.get("name", ""): d for d in corpus_docs if d.get("name")
        }
        for d in docs:
            name = d.get("name", "")
            if not name or _is_listing_title(name):
                continue
            if name in by_name:
                merged = dict(by_name[name])
                for key, value in d.items():
                    if value:
                        merged[key] = value
                by_name[name] = merged
            else:
                by_name[name] = d
        # 只改日期/交通等最小调整时没有新检索结果，必须保留旧行程内容。
        for day in plan.get("days", []) or []:
            for f in day.get("dining", []) or []:
                fname = f.get("name", "")
                if fname and fname not in by_name and not _is_listing_title(fname):
                    by_name[fname] = dict(f)
            for a in day.get("attractions", []) or []:
                aname = a.get("name", "")
                if aname and aname not in by_name and not _is_listing_title(aname):
                    by_name[aname] = dict(a)
        food_names = {
            name for name, d in by_name.items() if d.get("category") == "food"
        }
        non_attraction_names = {
            name
            for name, d in by_name.items()
            if d.get("category") in ("transport", "guide")
        }
        non_food_names = {
            name
            for name, d in by_name.items()
            if d.get("category") in ("attraction", "transport", "guide")
        }

        for day in plan.get("days", []):
            seen_attractions = set()
            seen_dining = set()
            kept = []
            dining = day.setdefault("dining", [])
            if isinstance(dining, dict):
                flattened = []
                for items in dining.values():
                    if isinstance(items, list):
                        flattened.extend(items)
                    elif isinstance(items, dict):
                        flattened.append(items)
                dining = flattened
                day["dining"] = dining
            deduped_dining = []
            for f in dining:
                fname = f.get("name", "")
                if (
                    not fname
                    or _is_listing_title(fname)
                    or fname not in by_name
                    or fname in seen_dining
                    or fname in non_food_names
                ):
                    continue
                doc = by_name.get(fname, {})
                item = dict(f)
                item["price"] = (
                    f.get("price")
                    or f.get("budget")
                    or f.get("fee")
                    or doc.get("fee", doc.get("price", 0))
                )
                if not item.get("address"):
                    item["address"] = doc.get("address", "")
                if not item.get("note"):
                    item["note"] = doc.get("note", "")
                seen_dining.add(fname)
                deduped_dining.append(item)
            for item in day.get("attractions", []):
                name = item.get("name", "")
                if (
                    not name
                    or _is_listing_title(name)
                    or name not in by_name
                    or name in seen_attractions
                ):
                    continue
                if any(
                    k in name
                    for k in (
                        "攻略",
                        "大全",
                        "地图",
                        "搜索",
                        "简书",
                        "马蜂窝",
                        "去哪儿",
                        "携程",
                        "穷游",
                        "知乎",
                        "点评",
                        "景点推荐",
                    )
                ):
                    continue
                if name in food_names:
                    if name not in seen_dining:
                        doc = by_name.get(name, {})
                        deduped_dining.append(
                            {
                                "name": name,
                                "price": item.get("price")
                                or item.get("budget")
                                or item.get("fee")
                                or doc.get("fee", doc.get("price", 0)),
                                "note": item.get("note") or doc.get("note", ""),
                            }
                        )
                        seen_dining.add(name)
                    continue
                if name in non_attraction_names:
                    continue
                seen_attractions.add(name)
                kept.append(item)
            kept_names = {a.get("name", "") for a in kept}
            day["attractions"] = kept
            day["dining"] = deduped_dining
            day["activities"] = [
                a for a in day.get("activities", []) if a.get("name") in kept_names
            ]
        for day in plan.get("days", []):
            for item in day.get("attractions", []):
                doc = by_name.get(item.get("name", ""))
                if doc and (item.get("lat") is None or item.get("lon") is None):
                    item["lat"] = doc.get("lat")
                    item["lon"] = doc.get("lon")
        expected_days = int((plan.get("params") or {}).get("days", 0) or 0)
        if expected_days and len(plan.get("days", []) or []) < expected_days:
            base = build_itinerary(plan.get("params"), docs)
            base_days = base.get("days", []) or []
            current = plan.get("days", []) or []
            for i in range(len(current), expected_days):
                day = dict(base_days[i]) if i < len(base_days) else dict(current[-1])
                day["day"] = i + 1
                current.append(day)
            plan["days"] = current

        from app.tools.geo import autocorrect_plan

        plan = _diversify_days(plan)
        plan = _ensure_min_spend(plan, docs, plan.get("params") or {})
        plan = _enforce_budget(plan)
        plan = _decorate_plan(plan)
        plan = autocorrect_plan(plan)
        return _refresh_timeline(plan)
