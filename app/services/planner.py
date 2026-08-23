"""行程规划领域服务：参数提取、意图识别、生成、调整、校验与格式化。"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any

from app.corpus import CITIES, build_docs
from app.data_registry import level_label, official_site
from app.rag.search import HybridSearcher
def _to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value).replace(",", ""))
    return int(m.group()) if m else default


from app.tools.geo import (
    autocorrect_plan,
    haversine_km,
    optimize_route,
    route_legs,
)

_FOOD_PRICE_MAP = {
    d.get("name", ""): _to_int(d.get("fee") or d.get("price") or 0)
    for d in build_docs()
    if d.get("category") == "food"
}


_LISTING_WORDS = ("推荐", "攻略", "盘点", "大全", "总结", "必試", "必试", "必尝", "必食", "榜单", "排行", "指南", "提到", "附近", "必吃", "必打卡", "哪些", "老味道", "百年老", "吃播", "探店", "網紅", "網紅店", "客滿", "鍋氣", "值得体验", "值得", "種草", "實測", "實拍", "開箱", "食記", "VLOG", "vlog", "打卡", "清单", "私藏", "本地人", "宝藏", "隐藏", "小众", "懒人包", "吃喝", "玩樂", "餐饮食材", "必去", "10 大", "10大", "十大", "TOP", "top", "前10", "老字號", "自由探索", "特色美食", "当地风味", "参考", "随便")


def _is_listing_name(name: str) -> bool:
    if any(k in name for k in _LISTING_WORDS):
        return True
    if re.search(r"\d+\s*家", name):
        return True
    hints = ("店", "馆", "楼", "庄", "餐厅", "老字号", "老字號", "铺", "坊")
    return len(name) > 12 and not any(h in name for h in hints)


def _default_food_price(name: str) -> int:
    if any(k in name for k in ("火锅", "涮肉", "烤鸭", "烧烤", "烤羊", "烤肉", "牛排", "海鲜", "自助")):
        return 120
    if any(k in name for k in ("小吃", "糖葫芦", "豆汁", "煎饼", "凉皮", "肉夹馍", "锅贴")):
        return 30
    if any(k in name for k in ("小笼", "生煎", "灌汤包", "包子", "饺子", "面", "馄饨", "抄手")):
        return 35
    if any(k in name for k in ("甜品", "奶茶", "咖啡", "蛋糕", "冰淇淋")):
        return 25
    return 60


def _search_url(keyword: str) -> str:
    from urllib.parse import quote

    return f"https://www.baidu.com/s?wd={quote(keyword)}"


def _short_intro(name: str, note: str, city: str, kind: str) -> str:
    note = (note or "").strip()
    if note and note not in (
        "来自多平台搜索，需人工复核",
        "由公开内容源抓取，需人工复核",
    ):
        return note
    return f"{name}是{city}值得体验的{kind}，建议结合当天行程安排。"


def _fill_empty_days(plan: dict[str, Any]) -> dict[str, Any]:
    """保证每天都有景点，第 3/4 天不再出现空白。"""
    all_attrs = [
        a
        for day in plan.get("days", []) or []
        for a in day.get("attractions", []) or []
    ]
    if not all_attrs:
        city = plan.get("city", "")
        all_attrs = [
            {
                "name": f"{city}城市自由探索",
                "category": "attraction",
                "note": "可在城市中心自由探索，结合当天美食体验",
                "duration_hours": 3,
                "fee": 0,
                "opening_hours": "全天",
            }
        ]
    all_foods = [
        f
        for day in plan.get("days", []) or []
        for f in day.get("dining", []) or []
    ]
    if not all_foods:
        city = plan.get("city", "")
        all_foods = [
            {
                "name": f"{city}特色美食",
                "price": 60,
                "price_source": "估算价",
                "note": "可按预算自行选择当地特色餐厅",
            }
        ]
    city = plan.get("city", "")
    used_food_names = {
        f.get("name", "")
        for day in plan.get("days", []) or []
        for f in day.get("dining", []) or []
        if isinstance(f, dict) and f.get("name")
    }
    food_pool = [
        dict(f)
        for f in all_foods
        if f.get("name") and f.get("name") not in used_food_names
    ]
    if not food_pool:
        for d in build_docs():
            name = d.get("name", "")
            if (
                d.get("category") == "food"
                and d.get("city") == city
                and name
                and name not in used_food_names
            ):
                food_pool.append(
                    {
                        "name": name,
                        "price": _to_int(d.get("fee") or d.get("price") or 0) or 60,
                        "price_source": (
                            "真实参考价" if (d.get("fee") or d.get("price")) else "估算价"
                        ),
                        "note": d.get("note", ""),
                    }
                )
    idx = 0
    used_attr_names = {
        a.get("name", "")
        for day in plan.get("days", []) or []
        for a in day.get("attractions", []) or []
        if a.get("name")
    }
    for day in plan.get("days", []) or []:
        if not day.get("attractions"):
            attr = all_attrs[idx % len(all_attrs)]
            name = attr.get("name", "")
            day["attractions"] = [dict(attr)]
            day["activities"] = [
                {
                    "name": name,
                    "duration_hours": attr.get("duration_hours", 2),
                    "opening_hours": attr.get("opening_hours", "全天"),
                    "fee": attr.get("fee", 0),
                    "note": attr.get("note", ""),
                }
            ]
            day["note"] = "已自动补充当日游览内容，可按需调整"
            used_attr_names.add(name)
            idx += 1
        while len(day.get("dining", []) or []) < 3:
            if not food_pool:
                food_pool = [dict(f) for f in all_foods]
            food = food_pool.pop(0)
            day.setdefault("dining", []).append(food)
    return plan


def _decorate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    plan = _fill_empty_days(plan)
    city = plan.get("city", "")
    for day in plan.get("days", []):
        raw_dining = day.get("dining") or []
        if isinstance(raw_dining, dict):
            flattened = []
            for items in raw_dining.values():
                if isinstance(items, list):
                    flattened.extend(items)
                elif isinstance(items, dict):
                    flattened.append(items)
            raw_dining = flattened
        day["dining"] = [
            item
            for item in raw_dining
            if isinstance(item, dict)
            and not _is_listing_name(str(item.get("name", "")))
        ]
        for item in day.get("dining", []):
            item.pop("meal_type", None)
            item.pop("meal", None)
            item["restaurant"] = item.get("restaurant") or item.get("title") or ""
            address = item.get("address") or ""
            if not address:
                content = str(item.get("content") or item.get("note") or "")
                m = re.search(r"(?:地址|location)[:：]?\s*([^\n，。;；]{4,60})", content)
                if m:
                    address = m.group(1).strip()
            item["address"] = address
            item["description"] = _short_intro(
                item.get("name", ""), item.get("note", ""), city, "美食"
            )
            raw_price = item.get("price") or item.get("budget") or item.get("fee")
            if raw_price:
                item["price"] = _to_int(raw_price)
                if not item.get("price_source"):
                    item["price_source"] = "真实参考价"
            else:
                content = str(item.get("content") or item.get("note") or "")
                m = re.search(r"¥\s*(\d{2,4})", content) or re.search(
                    r"(\d{2,4})\s*元", content
                )
                if m:
                    item["price"] = int(m.group(1))
                    item["price_source"] = "真实参考价"
                else:
                    item["price"] = int(
                        _FOOD_PRICE_MAP.get(item.get("name", ""), 0)
                        or _default_food_price(item.get("name", ""))
                    )
                    item["price_source"] = "估算价"
            source = str(item.get("price_source") or "")
            item["data_level"] = "C" if "估算" in source else "B"
            item["data_label"] = level_label(item["data_level"])
        for item in day.get("attractions", []):
            item["description"] = _short_intro(
                item.get("name", ""), item.get("note", ""), city, "景点"
            )
            site_url = official_site(str(item.get("name", "")))
            if site_url:
                item["official_url"] = site_url
                item["booking_required"] = True
                item["data_level"] = "A"
            else:
                item["data_level"] = "B"
            item["data_label"] = level_label(item["data_level"])
            if not item.get("fee"):
                content = str(item.get("content") or item.get("note") or "")
                m = re.search(r"(?:门票|票价)[:：]?\s*¥\s*(\d{1,4})", content) or re.search(
                    r"(?:门票|票价)[:：]?\s*(\d{1,4})\s*元", content
                )
                if m:
                    item["fee"] = int(m.group(1))
                    item["price_source"] = "真实参考价"
            item.setdefault(
                "official_url",
                item.get("url")
                or _search_url(f"{item.get('name', '')} {city} 门票 预约"),
            )
        for item in day.get("dining", []):
            item.setdefault(
                "map_url",
                item.get("url")
                or _search_url(f"{city} {item.get('name', '')}"),
            )
    return _refresh_timeline(plan)


def extract_departure_date(text: str) -> str | None:
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", text)
    if m:
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
    if m:
        today = date.today()
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
            return d.isoformat()
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})号", text)
    if m:
        today = date.today()
        day = int(m.group(1))
        try:
            d = date(today.year, today.month, day)
            if d >= today:
                return d.isoformat()
        except ValueError:
            pass
        month = today.month + 1
        year = today.year
        if month > 12:
            year += 1
            month = 1
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    today = date.today()
    if "后天" in text:
        return (today + timedelta(days=2)).isoformat()
    if "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    return None


_PROVINCE_CITY = {
    "福建": "福州",
    "广东": "广州",
    "浙江": "杭州",
    "江苏": "南京",
    "四川": "成都",
    "云南": "昆明",
    "陕西": "西安",
    "山东": "济南",
    "湖南": "长沙",
    "湖北": "武汉",
    "河南": "郑州",
    "河北": "石家庄",
    "山西": "太原",
    "辽宁": "沈阳",
    "吉林": "长春",
    "黑龙江": "哈尔滨",
    "安徽": "合肥",
    "江西": "南昌",
    "广西": "南宁",
    "贵州": "贵阳",
    "西藏": "拉萨",
    "甘肃": "兰州",
    "青海": "西宁",
    "宁夏": "银川",
    "新疆": "乌鲁木齐",
    "内蒙古": "呼和浩特",
    "海南": "海口",
    "台湾": "台北",
    "香港": "香港",
    "澳门": "澳门",
}


def normalize_city(city: str) -> str:
    return _PROVINCE_CITY.get(str(city or "").strip(), str(city or "").strip())


_CITY_ALIASES = {
    "福建": "福建",
    "福州": "福州",
    "厦门": "厦门",
    "广州": "广州",
    "深圳": "深圳",
    "杭州": "杭州",
    "西安": "西安",
    "重庆": "重庆",
    "南京": "南京",
    "武汉": "武汉",
    "长沙": "长沙",
    "青岛": "青岛",
    "大理": "大理",
    "丽江": "丽江",
    "三亚": "三亚",
    "桂林": "桂林",
    "哈尔滨": "哈尔滨",
    "长春": "长春",
    "沈阳": "沈阳",
    "呼和浩特": "呼和浩特",
    "石家庄": "石家庄",
    "太原": "太原",
    "郑州": "郑州",
    "济南": "济南",
    "合肥": "合肥",
    "南昌": "南昌",
    "南宁": "南宁",
    "海口": "海口",
    "昆明": "昆明",
    "贵阳": "贵阳",
    "拉萨": "拉萨",
    "兰州": "兰州",
    "西宁": "西宁",
    "银川": "银川",
    "乌鲁木齐": "乌鲁木齐",
    "苏州": "苏州",
    "无锡": "无锡",
    "宁波": "宁波",
    "温州": "温州",
    "泉州": "泉州",
    "珠海": "珠海",
    "大连": "大连",
    "烟台": "烟台",
    "威海": "威海",
    "洛阳": "洛阳",
    "开封": "开封",
    "黄山": "黄山",
    "景德镇": "景德镇",
    "张家界": "张家界",
    "敦煌": "敦煌",
    "西双版纳": "西双版纳",
    "香格里拉": "香格里拉",
}


def detect_city(text: str) -> str:
    for city in CITIES:
        if city in text:
            return city
    for alias, city in _CITY_ALIASES.items():
        if alias in text:
            return normalize_city(city)
    for alias, city in _PROVINCE_CITY.items():
        if alias in text:
            return normalize_city(city)
    return "北京"


def mentioned_city(text: str) -> str | None:
    for city in CITIES:
        if city in text:
            return city
    for alias, city in _CITY_ALIASES.items():
        if alias in text:
            return normalize_city(city)
    for alias, city in _PROVINCE_CITY.items():
        if alias in text:
            return normalize_city(city)
    return None


_CHINESE_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _parse_count(text: str, unit: str, default: int | None) -> int | None:
    m = re.search(rf"([0-9一二两三四五六七八九十]+)\s*个?\s*{unit}", text)
    if not m:
        return default
    raw = m.group(1)
    if raw.isdigit():
        return min(20, max(1, int(raw)))
    return _CHINESE_NUM.get(raw, default)


def extract_params(text: str) -> dict[str, Any]:
    explicit: list[str] = []

    days = _parse_count(text, "天", None)
    if days is not None:
        explicit.append("days")
    days = days or 2

    travelers = _parse_count(text, "人", None)
    if travelers is not None:
        explicit.append("travelers")
    travelers = travelers or 1

    min_spend: int | None = None
    for pattern in (
        r"(?:消费|花费|花|金额)\s*(?:不低于|不能低于|不得低于|至少|最少|达到|超过|高于|大于|以上)\s*(\d{3,6})",
        r"(?:不低于|不能低于|不得低于|至少|最少|最低)\s*(\d{3,6})\s*(?:元|块)?",
        r"(?:至少|最少|最低|必须)\s*(?:花|消费|花费)?\s*(\d{3,6})",
        r"花\s*(?:够|到|满|足)\s*(\d{3,6})",
        r"(\d{3,6})\s*元(?:以上|起)",
    ):
        m = re.search(pattern, text)
        if m:
            min_spend = int(m.group(1))
            explicit.append("min_spend")
            break

    budget: int | None = None
    for pattern in (
        r"(?:预算|不能超过|不超过|控制在|上限|最多)\s*(\d{3,6})\s*(?:元|块)?",
        r"(\d{3,6})\s*元以内",
        r"(\d{3,6})\s*以内",
        r"(\d{3,6})\s*元",
    ):
        m = re.search(pattern, text)
        if m:
            amount = int(m.group(1))
            if min_spend and amount == min_spend:
                continue
            budget = amount
            explicit.append("budget")
            break
            break

    transport_explicit = False
    transport = "自动"
    if any(k in text for k in ("自驾", "租车", "开车")):
        transport = "自驾"
        transport_explicit = True
    elif any(k in text for k in ("高铁", "动车")):
        transport = "高铁"
        transport_explicit = True
    elif any(k in text for k in ("公交", "地铁")):
        transport = "公共交通"
        transport_explicit = True
    elif any(k in text for k in ("打车", "出租车")):
        transport = "打车"
        transport_explicit = True
    elif any(k in text for k in ("共享", "骑行", "自行车")):
        transport = "共享单车"
        transport_explicit = True
    elif "自动" in text:
        transport = "自动"
        transport_explicit = True

    interests = []
    mapping = {
        "美食": ["美食"],
        "火锅": ["美食"],
        "历史": ["历史", "文化"],
        "文化": ["历史", "文化"],
        "亲子": ["亲子"],
        "拍照": ["拍照"],
        "自然": ["自然"],
        "轻松": ["轻松"],
    }
    for key, tags in mapping.items():
        if key in text:
            interests.extend(tags)
    if not interests:
        interests = ["拍照", "美食"]

    if mentioned_city(text):
        explicit.append("city")

    departure_date = extract_departure_date(text)
    if departure_date:
        explicit.append("departure_date")
    else:
        departure_date = (date.today() + timedelta(days=1)).isoformat()

    if transport_explicit:
        explicit.append("transport")

    return {
        "city": detect_city(text),
        "days": days,
        "travelers": travelers,
        "budget": budget,
        "min_spend": min_spend,
        "transport": transport,
        "interests": list(dict.fromkeys(interests)),
        "departure_date": departure_date,
        "source_text": text[:200],
        "_explicit_fields": explicit,
    }


def detect_intent(text: str, has_trip: bool = False) -> str:
    if extract_departure_date(text) and has_trip:
        return "adjust"
    adjust_words = (
        "调整",
        "改一下",
        "改",
        "轻松",
        "增加",
        "加",
        "不要",
        "不想",
        "不去",
        "去掉",
        "删",
        "附近",
        "提前",
        "延后",
        "换",
        "减少",
        "消费",
        "太少",
        "金额",
        "预算",
        "花费",
    )
    if any(w in text for w in adjust_words) and has_trip:
        return "adjust"
    if any(w in text for w in ("推荐", "攻略", "吃什么", "玩什么", "必吃", "怎么玩", "怎么", "介绍", "怎么样")):
        return "ask"
    if any(w in text for w in ("谢谢", "你好", "hi", "hello")):
        return "chat"
    return "create"


def _rank_docs(docs: list[dict], interests: list[str]) -> list[dict]:
    def weight(doc):
        score = doc.get("score", 0)
        for tag in interests:
            if tag in doc.get("tags", []):
                score += 0.2
        return score

    return sorted(docs, key=weight, reverse=True)


def _transport_units(mode: str, travelers: int) -> int:
    travelers = max(1, int(travelers or 1))
    if mode in ("打车", "驾车", "出租车", "car", "drive"):
        return max(1, math.ceil(travelers / 4))
    if mode in ("公共交通", "公交", "地铁", "共享单车", "骑行", "bus", "ride"):
        return travelers
    return 1


def _transport_cost(items: list[dict[str, Any]], travelers: int) -> int:
    legs = [x for x in items if x.get("cost_yuan")]
    if not legs:
        return 0
    total = 0
    for leg in legs:
        cost = int(leg.get("cost_yuan") or 0)
        mode = _mode_cn(leg.get("mode") or "")
        total += cost * _transport_units(mode, travelers)
    return int(total)


def _recompute_costs(plan: dict[str, Any]) -> dict[str, Any]:
    """按天重算消费，并汇总总消费。"""
    daily_totals = []
    travelers = max(1, int((plan.get("params") or {}).get("travelers", 1) or 1))
    hotel_total = _to_int(
        (plan.get("hotel") or {}).get("total_price")
        or (plan.get("hotel") or {}).get("price")
        or 0
    )
    for day_index, day in enumerate(plan.get("days", [])):
        attractions = sum(_to_int(a.get("fee") or a.get("budget") or 0) for a in day.get("attractions", [])) * travelers
        dining = sum(_to_int(f.get("price") or f.get("budget") or f.get("fee") or _FOOD_PRICE_MAP.get(f.get("name", ""), 0)) for f in day.get("dining", [])) * travelers
        timeline = day.get("timeline") or []
        legs = timeline if timeline else (day.get("route", []) or [])
        transport = _transport_cost(legs, travelers)
        if not legs:
            transport = 60 * travelers
        hotel = hotel_total if day_index == 0 else 0
        daily_totals.append(
            {
                "day": day.get("day"),
                "attractions": attractions,
                "dining": dining,
                "transport": transport,
                "hotel": hotel,
                "total": attractions + dining + transport + hotel,
            }
        )
    total_attractions = sum(item["attractions"] for item in daily_totals)
    total_dining = sum(item["dining"] for item in daily_totals)
    total_transport = sum(item["transport"] for item in daily_totals)
    old_budget = plan.get("budget", {})
    plan["budget"] = {
        "per_person": old_budget.get("per_person", 500),
        "daily_totals": daily_totals,
        "attractions": total_attractions,
        "dining": total_dining,
        "transport": total_transport,
        "hotel": hotel_total,
        "min_spend": _to_int((plan.get("params") or {}).get("min_spend") or 0),
        "estimated_total": total_attractions + total_dining + total_transport + hotel_total,
    }
    for key in ("spend_mode", "max_consumption", "amount_constrained"):
        if key in old_budget:
            plan["budget"][key] = old_budget[key]
    plan["budget"]["max_consumption"] = plan["budget"]["estimated_total"]
    plan["budget"]["amount_constrained"] = bool(
        _to_int((plan.get("params") or {}).get("budget") or 0)
        or _to_int((plan.get("params") or {}).get("min_spend") or 0)
    )
    min_spend_value = _to_int((plan.get("params") or {}).get("min_spend") or 0)
    if min_spend_value > 0:
        plan["budget"]["within_min_spend"] = (
            int(plan["budget"]["estimated_total"]) >= min_spend_value
        )
    budget_value = (plan.get("params") or {}).get("budget")
    if budget_value not in (None, "", 0):
        within = int(plan["budget"]["estimated_total"]) <= int(budget_value)
        plan["budget"]["within_budget"] = within
        if not within:
            issues = plan.setdefault("validation_issues", [])
            issue = f"超出预算：{plan['budget']['estimated_total']} > {budget_value}"
            if issue not in issues:
                issues.append(issue)
    else:
        plan["budget"]["within_budget"] = True
    return plan


def _enforce_min_spend(
    plan: dict[str, Any], docs: list[dict] | None = None
) -> dict[str, Any]:
    """最低消费约束：不足时补充推荐景点/美食，直到达到 min_spend。"""
    params = plan.get("params") or {}
    min_spend = _to_int(params.get("min_spend") or 0)
    if min_spend <= 0:
        return plan
    plan = _recompute_costs(plan)
    budget_value = params.get("budget")
    if budget_value not in (None, "", 0) and min_spend > int(budget_value):
        issues = plan.setdefault("validation_issues", [])
        issue = f"最低消费 {min_spend} 高于预算 {budget_value}，无法同时满足"
        if issue not in issues:
            issues.append(issue)
        return plan
    docs = docs or []
    city = plan.get("city") or params.get("city") or ""
    used = {
        a.get("name")
        for day in plan.get("days", []) or []
        for a in day.get("attractions", []) or []
    } | {
        f.get("name")
        for day in plan.get("days", []) or []
        for f in day.get("dining", []) or []
    }
    guard = 0
    while int(plan["budget"].get("estimated_total", 0)) < min_spend and guard < 30:
        candidates = [
            d
            for d in docs
            if d.get("name")
            and d.get("name") not in used
            and d.get("category") in ("attraction", "food")
            and (not d.get("city") or d.get("city") == city)
        ]
        candidates.sort(key=lambda d: -_to_int(d.get("fee") or d.get("price") or 0))
        if not candidates:
            candidates = [
                d
                for d in build_docs()
                if d.get("name")
                and d.get("name") not in used
                and d.get("category") in ("attraction", "food")
                and (not d.get("city") or d.get("city") == city)
            ]
            candidates.sort(key=lambda d: -_to_int(d.get("fee") or d.get("price") or 0))
        if not candidates:
            break
        doc = candidates[0]
        used.add(doc.get("name"))
        day = (plan.get("days") or [{}])[0]
        if doc.get("category") == "attraction":
            item = {
                "name": doc.get("name", ""),
                "category": "attraction",
                "fee": _to_int(doc.get("fee") or doc.get("budget") or 0),
                "duration_hours": doc.get("duration_hours", 2),
                "opening_hours": doc.get("opening_hours", "全天"),
                "note": doc.get("note", ""),
                "source": doc.get("source", ""),
            }
            day.setdefault("attractions", []).append(item)
            day.setdefault("activities", []).append(
                {
                    "name": item["name"],
                    "duration_hours": item["duration_hours"],
                    "opening_hours": item["opening_hours"],
                    "fee": item["fee"],
                    "note": item["note"],
                }
            )
        elif doc.get("category") == "food":
            day.setdefault("dining", []).append(
                {
                    "name": doc.get("name", ""),
                    "category": "food",
                    "price": _to_int(
                        doc.get("fee") or doc.get("price") or doc.get("budget") or 0
                    ),
                    "note": doc.get("note", ""),
                    "source": doc.get("source", ""),
                }
            )
        plan = _recompute_costs(plan)
        guard += 1
    plan["budget"]["min_spend"] = min_spend
    plan["budget"]["within_min_spend"] = (
        int(plan["budget"].get("estimated_total", 0)) >= min_spend
    )
    return plan
def _enforce_budget(
    plan: dict[str, Any], docs: list[dict] | None = None
) -> dict[str, Any]:
    """预算与最低消费硬约束：不超上限、不低于最低消费。"""
    plan = _recompute_costs(plan)
    min_spend = _to_int((plan.get("params") or {}).get("min_spend") or 0)
    max_budget = _to_int((plan.get("params") or {}).get("budget") or 0)
    if min_spend <= 0 and max_budget <= 0:
        plan["budget"]["spend_mode"] = "guide_recommended"
        plan["budget"]["amount_constrained"] = False
        return plan
    if min_spend > 0:
        plan = _enforce_min_spend(plan, docs)
        plan = _recompute_costs(plan)
    budget_value = plan.get("params", {}).get("budget")
    if budget_value is None or budget_value in (0, "", "0"):
        return plan
    budget = int(budget_value)
    costs = plan["budget"]
    def total_cost() -> int:
        return int(costs.get("attractions", 0)) + int(
            costs.get("dining", 0)
        ) + int(costs.get("transport", 0)) + int(costs.get("hotel", 0))
    while total_cost() > budget:
        best = None  # (day, index, fee)
        for day in plan.get("days", []):
            for idx, item in enumerate(day.get("attractions", [])):
                fee = _to_int(item.get("fee", 0))
                if fee > 0 and (best is None or fee > best[2]):
                    if min_spend > 0 and total_cost() - fee < min_spend:
                        continue
                    best = (day, idx, fee)
        if best:
            day, idx, fee = best
            name = day["attractions"][idx]["name"]
            day["attractions"].pop(idx)
            day["activities"] = [
                a for a in day.get("activities", []) if a.get("name") != name
            ]
            plan = _recompute_costs(plan)
            costs = plan["budget"]
            continue
        best_food = None
        for day in plan.get("days", []):
            for idx, food in enumerate(day.get("dining", [])):
                price = _to_int(food.get("price") or food.get("budget") or 0)
                if price > 0 and (best_food is None or price > best_food[2]):
                    if min_spend > 0 and total_cost() - price < min_spend:
                        continue
                    best_food = (day, idx, price)
        if best_food:
            day, idx, price = best_food
            day["dining"].pop(idx)
            plan = _recompute_costs(plan)
            costs = plan["budget"]
            continue
        break
    costs["estimated_total"] = total_cost()
    costs["within_budget"] = total_cost() <= budget
    if not costs["within_budget"]:
        issues = plan.setdefault("validation_issues", [])
        if "超出预算" not in issues:
            issues.append(f"超出预算：{total_cost()} > {budget}")
    return autocorrect_plan(plan)
_LOW_SPEND_WORDS = ("省钱", "便宜", "少花", "节约", "控制预算", "不要太贵", "尽量少", "预算低", "少一点")


def _matches_removal(name: str, instruction: str) -> bool:
    """支持“故宫”匹配“故宫博物院”这类简称删除。"""
    if not name:
        return False
    if name in instruction:
        return True
    for i in range(len(instruction) - 1):
        if instruction[i : i + 2] in name:
            return True
    return False


def _ensure_min_spend(
    plan: dict[str, Any], docs: list[dict], params: dict[str, Any]
) -> dict[str, Any]:
    """默认把所有推荐景点和美食排进行程，按最高消费估算；省钱时保留核心项。"""
    source = str(params.get("source_text", "") or plan.get("params", {}).get("source_text", ""))
    if any(w in source for w in _LOW_SPEND_WORDS):
        plan = _recompute_costs(plan)
        plan["budget"]["spend_mode"] = "core_only"
        plan["budget"]["max_consumption"] = int(plan["budget"].get("estimated_total", 0))
        return plan

    plan = _recompute_costs(plan)
    city = plan.get("city", params.get("city", ""))
    available_attractions = [
        d
        for d in docs
        if d.get("category") == "attraction" and d.get("city") == city
    ]
    available_foods = [
        d
        for d in docs
        if d.get("category") == "food" and d.get("city") == city
    ]

    days = plan.get("days", [])
    if not days:
        plan["budget"]["spend_mode"] = "all_recommended"
        plan["budget"]["max_consumption"] = int(plan["budget"].get("estimated_total", 0))
        return plan

    ranked_attractions = sorted(
        available_attractions, key=lambda d: d.get("score", 0), reverse=True
    )
    used_attrs: set[str] = set()
    for day in days:
        day.setdefault("attractions", [])
        day.setdefault("activities", [])
        current = {a.get("name", "") for a in day["attractions"]}
        while len(day["attractions"]) < 3:
            candidates = [
                d
                for d in ranked_attractions
                if d.get("name") and d.get("name") not in current and d.get("name") not in used_attrs
            ]
            if not candidates:
                candidates = [
                    d for d in ranked_attractions if d.get("name") and d.get("name") not in current
                ]
            if not candidates:
                break
            doc = candidates[0]
            day["attractions"].append(doc)
            day["activities"].append(
                {
                    "name": doc.get("name"),
                    "duration_hours": doc.get("duration_hours", 2),
                    "opening_hours": doc.get("opening_hours", "全天"),
                    "fee": doc.get("fee", doc.get("budget", 0)),
                    "note": doc.get("note", ""),
                }
            )
            current.add(doc.get("name"))
            used_attrs.add(doc.get("name"))

    used_foods: set[str] = set()
    for day in days:
        day.setdefault("dining", [])
        current = {f.get("name", "") for f in day["dining"]}
        while len(day["dining"]) < 3:
            candidates = [
                d
                for d in available_foods
                if d.get("name") and d.get("name") not in current and d.get("name") not in used_foods
            ]
            if not candidates:
                candidates = [
                    d for d in available_foods if d.get("name") and d.get("name") not in current
                ]
            if not candidates:
                break
            doc = candidates[0]
            day["dining"].append(
                {
                    "name": doc.get("name"),
                    "price": doc.get("fee", doc.get("price", doc.get("budget", 0))),
                    "food_type": doc.get("food_type") or "",
                    "lat": doc.get("lat", ""),
                    "lon": doc.get("lon", ""),
                    "note": doc.get("note", ""),
                }
            )
            current.add(doc.get("name"))
            used_foods.add(doc.get("name"))

    plan = _recompute_costs(plan)
    total = int(plan["budget"].get("estimated_total", 0))
    plan["budget"]["spend_mode"] = "all_recommended"
    plan["budget"]["max_consumption"] = total
    plan["adjustment_note"] = "已为你整理全部推荐景点与美食"
    return plan

def build_itinerary(
    params: dict[str, Any], docs: list[dict], searcher: HybridSearcher | None = None
) -> dict[str, Any]:
    searcher = searcher or HybridSearcher()
    city = params.get("city", "北京") or "北京"
    total_days = max(1, int(params.get("days", 2) or 2))
    travelers = max(1, int(params.get("travelers", 1) or 1))
    params = {**params, "city": city, "days": total_days, "travelers": travelers}
    interests = params.get("interests", [])
    city_docs = [d for d in docs if d.get("city") == city]
    attractions = _rank_docs(
        [d for d in city_docs if d.get("category") == "attraction"], interests
    )
    foods = [d for d in city_docs if d.get("category") == "food"]
    hubs = [d for d in city_docs if d.get("category") == "transport"]

    per_day = 3 if "轻松" not in interests else 2
    if not attractions:
        attractions = [
            {
                "name": f"{city}城市自由探索",
                "category": "attraction",
                "note": "可在城市中心自由探索，结合当天美食体验",
                "duration_hours": 3,
                "fee": 0,
                "opening_hours": "全天",
            }
        ]
    while len(attractions) < total_days * per_day:
        attractions = attractions + attractions[: total_days * per_day - len(attractions)]
    plan_days = []
    for i in range(total_days):
        slice_start = i * per_day
        day_items = attractions[slice_start : slice_start + per_day]
        if not day_items:
            day_items = attractions[:per_day]
        daily_food = foods[(i * 2) % max(1, len(foods)) : (i * 2) % max(1, len(foods)) + 2]
        if not daily_food:
            daily_food = foods[:2]
        ordered = optimize_route(day_items)
        theme = " / ".join(dict.fromkeys(t for item in day_items for t in item.get("tags", []) if t in interests)) or "城市漫游"
        plan_days.append(
            {
                "day": i + 1,
                "theme": theme,
                "attractions": ordered,
                "activities": [
                    {
                        "name": item.get("name"),
                        "duration_hours": item.get("duration_hours", 2),
                        "opening_hours": item.get("opening_hours", "全天"),
                        "fee": item.get("fee", 0),
                        "note": item.get("note", ""),
                    }
                    for item in ordered
                ],
                "dining": [
                    {
                        "name": food.get("name"),
                        "price": food.get("fee", food.get("price", 0)),
                        "food_type": food.get("food_type") or "",
                        "lat": food.get("lat", ""),
                        "lon": food.get("lon", ""),
                        "note": food.get("note", ""),
                    }
                    for food in daily_food
                ],
                "transport": [
                    {
                        "mode": params.get("transport", "自动"),
                        "note": "根据距离矩阵自动优化",
                    }
                ],
                "route": route_legs(ordered),
            }
        )

    budget_per_person = max(300, int((params.get("budget") or 3000) / total_days))
    plan = {
        "city": city,
        "summary": f"{city} {total_days} 日 {travelers} 人行程",
        "params": params,
        "days": plan_days,
        "transport_hub": hubs[0] if hubs else None,
        "budget": {
            "per_person": budget_per_person,
        },
        "sources": sorted(
            {d.get("source") for d in city_docs if d.get("source")}
        ),
    }
    plan = autocorrect_plan(plan)
    plan = _ensure_min_spend(plan, docs, params)
    plan = _decorate_plan(plan)
    plan = _enforce_budget(plan, docs)
    return _refresh_timeline(plan)
def _increase_spending(
    plan: dict[str, Any],
    docs: list[dict],
    params: dict[str, Any],
) -> dict[str, Any]:
    """消费太少时：把所有推荐景点和美食补进行程，预算内取最高消费。"""
    plan = _ensure_min_spend(plan, docs, params)
    plan["adjustment_note"] = "已按“消费太少”补充推荐景点和美食"
    return _enforce_budget(plan, docs)

def apply_adjustment(
    plan: dict[str, Any],
    instruction: str,
    docs: list[dict],
    params: dict[str, Any],
) -> dict[str, Any]:
    """局部重规划：根据自然语言修改现有行程，避免全量重生成。"""
    plan = {**plan, "params": {**(plan.get("params") or {}), **params}}
    days = plan.get("days", [])
    existing_days = len(days)
    new_days = int(plan["params"].get("days", existing_days))
    if "增加一天" in instruction:
        new_days = existing_days + 1
    elif "减少一天" in instruction:
        new_days = existing_days - 1
    if new_days != existing_days:
        new_days = max(1, min(7, new_days))
        if new_days < existing_days:
            days = days[:new_days]
        else:
            base_plan = build_itinerary(plan["params"], docs)
            base_days = base_plan.get("days", [])
            for i in range(existing_days, new_days):
                if i < len(base_days):
                    days.append({**base_days[i], "day": i + 1})
                else:
                    last = dict(days[-1]) if days else {}
                    last["day"] = i + 1
                    days.append(last)
        for idx, day in enumerate(days):
            day["day"] = idx + 1
        plan["summary"] = (
            f"{plan.get('city', '')} {new_days} 日 "
            f"{plan['params'].get('travelers', 1)} 人行程"
        )

    if plan.get("city") and params.get("city") and plan["city"] != params["city"]:
        plan = build_itinerary(params, docs)
        plan["adjustment_note"] = "已按新的城市要求重新规划当前行程"
        plan = autocorrect_plan(plan)
        plan = _ensure_min_spend(plan, docs, params)
        return _enforce_budget(plan, docs)

    if any(k in instruction for k in ("消费太少", "金额太少", "太便宜", "花得太少", "预算没用完")):
        return _increase_spending(plan, docs, params)

    if "轻松" in instruction:
        for day in days:
            if len(day.get("attractions", [])) > 2:
                day["attractions"] = day["attractions"][:2]
            day["activities"] = [
                {**a, "duration_hours": a.get("duration_hours", 2) + 1}
                for a in day.get("activities", [])
            ]
            day["note"] = "已按“轻松”模式放慢节奏，减少景点数量"

    if any(k in instruction for k in ("火锅", "美食", "烤鸭", "小笼", "生煎", "串串")):
        city = plan.get("city", params.get("city", ""))
        matched = [
            d for d in docs if d.get("city") == city and d.get("category") == "food"
        ]
        wanted = [
            d
            for d in matched
            if any(k in d.get("name", "") for k in ("火锅", "烤鸭", "小笼", "生煎", "串串"))
        ]
        if wanted and days:
            dining_names = {x.get("name") for x in days[0].get("dining", [])}
            for item in wanted:
                if item.get("name") not in dining_names:
                    days[0]["dining"].append(
                        {
                            "name": item.get("name"),
                            "price": item.get("fee", item.get("price", 0)),
                            "note": item.get("note", ""),
                        }
                    )

    if "附近" in instruction and "酒店" in instruction:
        last = days[-1]["attractions"][-1] if days and days[-1].get("attractions") else None
        days[-1]["hotel"] = {
            "name": f"{plan.get('city', '')}{last.get('name', '市中心')}附近推荐酒店",
            "distance_km": round(1.2, 1),
            "price": int(plan.get("budget", {}).get("per_person", 500) * 0.8),
            "note": "由地图 POI 工具生成，可按预算替换",
        }

    if "亲子" in instruction:
        city = plan.get("city", params.get("city", ""))
        panda = next(
            (d for d in docs if d.get("name") == "成都大熊猫繁育研究基地" and d.get("city") == city),
            None,
        )
        if panda and days and not any(
            a.get("name") == panda.get("name") for a in days[0].get("attractions", [])
        ):
            days[0]["attractions"].append(panda)
            days[0]["activities"].append(
                {
                    "name": panda.get("name"),
                    "duration_hours": panda.get("duration_hours", 3),
                    "opening_hours": panda.get("opening_hours", "全天"),
                    "fee": panda.get("fee", 0),
                    "note": panda.get("note", ""),
                }
            )

    if any(k in instruction for k in ("不要", "不想", "不去", "去掉", "删")):
        removed: set[str] = set()
        for day in days:
            kept = []
            for item in day.get("attractions", []):
                name = item.get("name", "")
                if _matches_removal(name, instruction):
                    removed.add(name)
                else:
                    kept.append(item)
            day["attractions"] = kept
            day["activities"] = [a for a in day.get("activities", []) if a.get("name") not in removed]
            day["dining"] = [
                f
                for f in day.get("dining", [])
                if not _matches_removal(f.get("name", ""), instruction)
            ]
        if removed:
            used = {
                a.get("name", "")
                for day in days
                for a in day.get("attractions", []) or []
            }
            candidates = [
                d
                for d in docs
                if d.get("category") == "attraction"
                and d.get("city") == plan.get("city")
                and d.get("name")
                and d.get("name") not in used
                and d.get("name") not in removed
            ]
            for day in days:
                while len(day.get("attractions", []) or []) < 3 and candidates:
                    doc = candidates.pop(0)
                    name = doc.get("name", "")
                    day.setdefault("attractions", []).append(doc)
                    day.setdefault("activities", []).append(
                        {
                            "name": name,
                            "duration_hours": doc.get("duration_hours", 2),
                            "opening_hours": doc.get("opening_hours", "全天"),
                            "fee": doc.get("fee", 0),
                            "note": doc.get("note", ""),
                        }
                    )
                    used.add(name)

    plan["days"] = days
    plan["adjustment_note"] = "已执行局部重规划，未全量重新生成"
    plan = autocorrect_plan(plan)
    return _enforce_budget(plan, docs)


def _mode_cn(mode: str) -> str:
    return {
        "auto": "自动推荐",
        "公共交通": "公共交通",
        "公交": "公交",
        "地铁": "地铁",
        "共享单车": "共享单车",
        "骑行": "骑行",
        "打车": "打车",
        "驾车": "驾车",
        "car": "打车",
        "bus": "公交",
        "ride": "骑行",
        "walk": "步行",
    }.get(str(mode or ""), str(mode or "自动推荐"))


def _format_clock(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}"


def _make_transport_leg(
    current: dict[str, Any],
    nxt: dict[str, Any],
    route_map: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    cur_title = str(current.get("name", ""))
    nxt_title = str(nxt.get("name", ""))
    leg = route_map.get((cur_title, nxt_title), {})
    mode = _mode_cn(leg.get("mode") or "auto")
    if leg:
        minutes = max(1, int(leg.get("minutes") or 30))
        cost = leg.get("cost_yuan")
        distance = leg.get("distance_km") or 0
        cost_source = "高德" if cost is not None else "估算"
    else:
        if (
            current.get("lat")
            and current.get("lon")
            and nxt.get("lat")
            and nxt.get("lon")
        ):
            try:
                d_km = haversine_km(
                    float(current.get("lat")),
                    float(current.get("lon")),
                    float(nxt.get("lat")),
                    float(nxt.get("lon")),
                )
            except (TypeError, ValueError):
                d_km = 0
        else:
            d_km = 0
        if not d_km:
            mode = "公共交通"
            minutes = 20
            cost = 3
        elif d_km < 1.2:
            mode = "步行"
            minutes = max(8, int(d_km / 5 * 60))
            cost = 0
        elif d_km and d_km < 3:
            mode = "共享单车"
            minutes = max(10, int(d_km / 15 * 60))
            cost = 2.5
        elif d_km and d_km < 8:
            mode = "公共交通"
            minutes = max(15, int(d_km / 25 * 60 + 10))
            cost = 3
        else:
            mode = "打车"
            minutes = max(20, int(d_km / 40 * 60 + 8))
            cost = round(13 + max(0, d_km - 3) * 2.3)
        distance = round(d_km, 1)
        cost_source = "估算"
    if cost is None:
        if mode in ("共享单车", "骑行"):
            cost = 2.5
        elif mode in ("打车", "驾车"):
            cost = round(13 + max(0, float(distance) - 3) * 2.3)
        else:
            cost = 3
    return (
        {
            "type": "transport",
            "title": f"前往 {nxt_title}",
            "mode": mode,
            "minutes": minutes,
            "cost_yuan": cost,
            "cost_source": cost_source,
            "advice": leg.get("advice") or "",
            "steps": leg.get("transit_steps") or [],
            "from": cur_title,
            "to": nxt_title,
            "from_lat": current.get("lat", ""),
            "from_lon": current.get("lon", ""),
            "to_lat": nxt.get("lat", ""),
            "to_lon": nxt.get("lon", ""),
            "data_level": "S" if cost_source == "高德" else "C",
            "data_label": level_label("S" if cost_source == "高德" else "C"),
        },
        minutes,
    )


def _build_day_timeline(day: dict[str, Any], city: str) -> list[dict[str, Any]]:
    attractions = day.get("attractions", []) or []
    dining = day.get("dining", []) or []
    route_map = {
        (str(leg.get("from")), str(leg.get("to"))): leg
        for leg in day.get("route", []) or []
    }
    timeline: list[dict[str, Any]] = []
    cursor = 9 * 60
    max_day_minutes = 22 * 60

    lunch = dining[0] if dining else None
    snack = dining[1] if len(dining) >= 2 else None
    dinner = dining[2] if len(dining) >= 3 else None
    extras = dining[3:]

    blocks: list[tuple[str, dict[str, Any], int, int]] = []
    if attractions:
        blocks.append(("attraction", attractions[0], 9 * 60, 180))
    if lunch:
        blocks.append(("food", lunch, 12 * 60 + 30, 55))
    if len(attractions) >= 2:
        blocks.append(("attraction", attractions[1], 0, 150))
    if snack:
        blocks.append(("food", snack, 15 * 60 + 30, 35))
    if len(attractions) >= 3:
        blocks.append(("attraction", attractions[2], 0, 150))
    if dinner:
        blocks.append(("food", dinner, 18 * 60 + 30, 55))
    for f in extras:
        blocks.append(("food", f, 20 * 60, 35))

    current_item: dict[str, Any] | None = None
    for kind, item, target_minutes, cap_minutes in blocks:
        if cursor >= max_day_minutes:
            break
        if current_item is not None:
            transport_item, minutes = _make_transport_leg(current_item, item, route_map)
            if cursor + minutes + 10 > max_day_minutes:
                break
            transport_item["time"] = _format_clock(cursor)
            timeline.append(transport_item)
            cursor += minutes

        if kind == "food":
            start = max(cursor, target_minutes or cursor)
            if start + cap_minutes + 15 > max_day_minutes:
                break
            cursor = start
            timeline.append(
                {
                    "time": _format_clock(cursor),
                    "type": "food",
                    "title": item.get("name", ""),
                    "restaurant": item.get("restaurant") or "",
                    "food_type": item.get("food_type") or "",
                    "address": item.get("address") or "",
                    "note": item.get("note") or item.get("description") or "",
                    "price": item.get("price") or 0,
                    "map_url": item.get("map_url") or item.get("url") or "",
                    "price_source": item.get("price_source", ""),
                }
            )
            cursor += cap_minutes
        else:
            duration_value = item.get("duration_hours", 3) or 3
            try:
                duration = min(max(float(duration_value) * 1.3, 1.5), cap_minutes / 60) * 60
            except (TypeError, ValueError):
                duration = min(cap_minutes, 180)
            duration = int(min(duration, cap_minutes))
            if cursor + duration + 15 > max_day_minutes:
                duration = max(60, max_day_minutes - cursor - 15)
            timeline.append(
                {
                    "time": _format_clock(cursor),
                    "type": "attraction",
                    "title": item.get("name", ""),
                    "note": item.get("note") or item.get("description") or "",
                    "url": item.get("official_url") or item.get("url") or "",
                    "price": item.get("fee") or item.get("budget") or 0,
                }
            )
            cursor += int(duration)
        current_item = item

    if timeline and cursor < max_day_minutes:
        cursor = min(cursor + 10, max_day_minutes)
        timeline.append(
            {
                "time": _format_clock(cursor),
                "type": "hotel_return",
                "title": "回酒店",
                "note": "返回酒店休息，整理当天行程与照片",
                "minutes": 0,
                "cost_yuan": None,
            }
        )

    return timeline


def _diversify_days(plan: dict[str, Any]) -> dict[str, Any]:
    days = plan.get("days", []) or []
    if len(days) < 2:
        return plan
    return plan


def _practical_tips(plan: dict[str, Any]) -> list[str]:
    city = plan.get("city", "")
    tips = [
        "热门景点建议提前 1-7 天在官方渠道预约购票",
        "随身携带身份证，交通、景区购票常用",
        "出行前查看当日天气，预留弹性时间",
    ]
    if city:
        tips.insert(0, f"{city} 早晚温差和节假日人流需要留意")
    return tips


def _packing_list(plan: dict[str, Any]) -> list[str]:
    items = ["身份证", "手机与充电宝", "常用药品"]
    for item in plan.get("weather", []) or []:
        text = str(item.get("text", ""))
        if "雨" in text:
            items.append("雨伞或雨衣")
        try:
            temp = float(item.get("temp_max", 0))
        except (TypeError, ValueError):
            temp = 0.0
        if temp >= 30:
            items.append("防晒霜、遮阳帽")
        if temp <= 10:
            items.append("保暖外套")
    return list(dict.fromkeys(items))


def _resolve_day_item(day: dict[str, Any], title: str) -> tuple[str, dict[str, Any]] | None:
    name = str(title or "").strip()
    if not name:
        return None
    for a in day.get("attractions", []) or []:
        an = str(a.get("name", "")).strip()
        if an and (an == name or an in name or name in an):
            return "attraction", a
    for f in day.get("dining", []) or []:
        fn = str(f.get("name", "")).strip()
        if fn and (fn == name or fn in name or name in fn):
            return "food", f
    return None


def _materialize_llm_timeline(
    day: dict[str, Any], activities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not activities:
        return []
    route_map = {
        (str(leg.get("from")), str(leg.get("to"))): leg
        for leg in day.get("route", []) or []
    }
    timeline: list[dict[str, Any]] = []
    prev_end = 9 * 60
    prev_full: dict[str, Any] | None = None
    max_day_minutes = 22 * 60

    seen_names: set[str] = set()
    for raw in activities:
        time_minutes = max(prev_end, int(raw.get("time_minutes", 9 * 60)))
        kind = raw.get("type", "")
        title = raw.get("title", "")
        if time_minutes >= max_day_minutes:
            break

        full = None
        if kind in ("attraction", "food"):
            resolved = _resolve_day_item(day, title)
            if not resolved:
                continue
            kind, full = resolved
            full_title = str(full.get("name", title)).strip()
            if full_title in seen_names:
                continue
            seen_names.add(full_title)
            duration = int(raw.get("duration_minutes", 0))
            if not duration:
                try:
                    duration = int(float(full.get("duration_hours", 2) or 2) * 60)
                except (TypeError, ValueError):
                    duration = 120
            if kind == "food":
                duration = max(30, min(duration, 90))
            else:
                duration = max(60, min(duration, 180))
            if prev_full is not None:
                leg_item, leg_minutes = _make_transport_leg(prev_full, full, route_map)
                needed = prev_end + leg_minutes
                if time_minutes < needed:
                    time_minutes = needed
                if time_minutes >= max_day_minutes:
                    break
                leg_item["minutes"] = leg_minutes
                leg_item["time"] = _format_clock(time_minutes - leg_minutes)
                timeline.append(leg_item)
        else:
            rest_title = str(title or "").strip()
            if "酒店" in rest_title or "回酒店" in rest_title:
                continue
            duration = max(20, min(int(raw.get("duration_minutes", 30)), 90))

        item = {
            "time": _format_clock(time_minutes),
            "type": kind,
            "title": full.get("name", title) if full else title,
            "duration_minutes": duration,
        }
        if kind == "food":
            item.update(
                {
                    "restaurant": full.get("restaurant") or "",
                    "food_type": full.get("food_type") or "",
                    "address": full.get("address") or "",
                    "note": raw.get("note") or full.get("note") or "",
                    "price": full.get("price") or 0,
                    "map_url": full.get("map_url") or full.get("url") or "",
                    "price_source": full.get("price_source", ""),
                }
            )
        elif kind == "attraction":
            item.update(
                {
                    "note": raw.get("note") or full.get("note") or full.get("description") or "",
                    "url": full.get("official_url") or full.get("url") or "",
                    "price": full.get("fee") or full.get("budget") or 0,
                }
            )
        else:
            item["note"] = raw.get("note") or "自由活动/休息"
        timeline.append(item)
        prev_end = time_minutes + duration
        if kind in ("attraction", "food"):
            prev_full = full

    food_count = sum(1 for x in timeline if x.get("type") == "food")
    if food_count < 2:
        return []

    if timeline and prev_end < max_day_minutes:
        hotel_time = min(prev_end + 10, max_day_minutes)
        timeline.append(
            {
                "time": _format_clock(hotel_time),
                "type": "hotel_return",
                "title": "回酒店",
                "note": "返回酒店休息，整理当天行程与照片",
                "minutes": 0,
                "cost_yuan": None,
            }
        )
    return timeline


def _refresh_timeline(plan: dict[str, Any]) -> dict[str, Any]:
    city = plan.get("city", "")
    for day in plan.get("days", []) or []:
        llm_timeline = day.get("llm_timeline") or []
        materialized = _materialize_llm_timeline(day, llm_timeline) if llm_timeline else []
        if materialized:
            day["timeline"] = materialized
        else:
            day["timeline"] = _build_day_timeline(day, city)
    plan["practical_tips"] = _practical_tips(plan)
    plan["packing_list"] = _packing_list(plan)
    return plan


def _merge_transport_legs(plan: dict[str, Any]) -> dict[str, Any]:
    """把高德真实路线结果合并到每天 route，覆盖内置估算的时长/费用/方式。"""
    legs = (plan.get("transport") or {}).get("legs", []) or []
    lookup = {(str(x.get("from")), str(x.get("to"))): x for x in legs}
    for day in plan.get("days", []) or []:
        for leg in day.get("route", []) or []:
            real = lookup.get((str(leg.get("from")), str(leg.get("to"))))
            if not real:
                continue
            for key in (
                "distance_km",
                "minutes",
                "mode",
                "cost_yuan",
                "advice",
                "from_lat",
                "from_lon",
                "to_lat",
                "to_lon",
                "engine",
                "transit_steps",
            ):
                if real.get(key) is not None:
                    leg[key] = real[key]
    return plan


def apply_reflection_tuning(plan: dict[str, Any]) -> dict[str, Any]:
    """反思结果不直接展示给用户，只用于系统内部自动调优。"""
    tuned = False
    for day in plan.get("days", []) or []:
        while len(day.get("attractions", []) or []) > 1:
            total = sum(leg.get("minutes", 0) for leg in day.get("route", []) or [])
            if total <= 240:
                break
            removed = day["attractions"].pop()
            name = removed.get("name", "")
            day["activities"] = [
                a for a in day.get("activities", []) or [] if a.get("name") != name
            ]
            day["route"] = []
            day["note"] = "已按内部优化建议精简路线，减少长距离折返"
            tuned = True
    if tuned:
        plan = autocorrect_plan(plan)
        plan = _recompute_costs(plan)
        plan = _enforce_budget(plan)
        plan["internal_tuned"] = True
    return plan


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    issues = list(plan.get("validation_issues", []))
    sources = plan.get("sources", [])
    if not sources:
        issues.append("缺少来源约束，禁止发布无来源内容")
    if not plan.get("days"):
        issues.append("行程为空")
    plan["validation_issues"] = issues
    plan["valid"] = not issues
    return plan


def format_reply(plan: dict[str, Any], intent: str) -> str:
    if intent == "ask":
        names = []
        for day in plan.get("days", []):
            names.extend(a.get("name", "") for a in day.get("attractions", []))
            names.extend(d.get("name", "") for d in day.get("dining", []))
        if not names:
            names = plan.get("sources", []) or ["内置语料"]
        return (
            f"根据 RAG 检索，{plan.get('city', '该城市')} 的推荐包括："
            f"{'、'.join(dict.fromkeys(names))}。"
            f"内容来源：{'、'.join(plan.get('sources', []) or ['内置语料'])}。"
        )
    if intent == "chat":
        return "好的，随时告诉我你想去哪里玩，我来帮你安排。"
    lines = [plan.get("summary", "行程规划完成"), ""]
    params = plan.get("params", {})
    lines.append(f"交通方式：{params.get('transport', '自动')}")
    if "轻松" in params.get("interests", []):
        lines.append("已按轻松模式安排，减少每日景点数量并拉长休息时间")
    lines.append("")
    for day in plan.get("days", []):
        names = " → ".join(
            a.get("name", "") for a in day.get("attractions", [])
        )
        foods = "、".join(d.get("name", "") for d in day.get("dining", []))
        budget_daily = next(
            (
                d.get("transport", 0)
                for d in (plan.get("budget") or {}).get("daily_totals", [])
                if d.get("day") == day.get("day")
            ),
            None,
        )
        if budget_daily is not None:
            day_transport = int(budget_daily or 0)
        else:
            day_transport = _transport_cost(
                day.get("route", []) or [], int(params.get("travelers", 1) or 1)
            )
            if not (day.get("route") or []):
                day_transport = 60 * int(params.get("travelers", 1) or 1)
        line = f"Day {day.get('day')} 【{day.get('theme', '漫游')}】{names}；餐饮：{foods}；交通：¥{day_transport}"
        if day.get("hotel"):
            line += f"；酒店：{day['hotel'].get('name')}"
        if day.get("note"):
            line += f"；{day['note']}"
        lines.append(line)
    lines.append("")
    lines.append("已通过规则校验与来源约束，可继续用自然语言调整。")
    return "\n".join(lines)

