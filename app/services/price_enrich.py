"""价格参考库注入：把人工维护/用户反馈价格合并进行程。"""

from __future__ import annotations

from typing import Any

from app.data_registry import level_label
from app.services.planner import _enforce_budget, _recompute_costs


def _apply_price(item: dict[str, Any], price_row: dict[str, Any]) -> None:
    price = float(price_row.get("price") or 0)
    if price <= 0:
        return
    source = str(price_row.get("source") or "reference")
    url = str(price_row.get("source_url") or "")
    if source == "官方" or source == "official":
        item["data_level"] = "A"
    elif source == "用户反馈":
        item["data_level"] = "D"
    else:
        item["data_level"] = "B"
    item["data_label"] = level_label(item["data_level"])
    item["price_source"] = f"{source}价格"
    item["price"] = int(round(price))
    item["fee"] = int(round(price))
    if url:
        item["official_url"] = url
    if price_row.get("note"):
        item["note"] = str(price_row.get("note"))


def enrich_plan_with_prices(plan: dict[str, Any], db: Any) -> dict[str, Any]:
    prices = db.list_place_prices(status="approved")
    if not prices:
        return plan
    city = str(plan.get("city") or "")
    for day in plan.get("days", []) or []:
        for item in day.get("attractions", []) or []:
            name = str(item.get("name") or "")
            row = next(
                (
                    p
                    for p in prices
                    if p.get("city") == city and (p.get("place_name") in name or name in p.get("place_name", ""))
                ),
                None,
            )
            if row:
                _apply_price(item, row)
        for item in day.get("dining", []) or []:
            name = str(item.get("name") or "")
            row = next(
                (
                    p
                    for p in prices
                    if p.get("city") == city and (p.get("place_name") in name or name in p.get("place_name", ""))
                ),
                None,
            )
            if row:
                _apply_price(item, row)
        for item in day.get("timeline", []) or []:
            name = str(item.get("title") or item.get("restaurant") or "")
            row = next(
                (
                    p
                    for p in prices
                    if p.get("city") == city and (p.get("place_name") in name or name in p.get("place_name", ""))
                ),
                None,
            )
            if row and item.get("type") in ("attraction", "food"):
                _apply_price(item, row)
    plan = _recompute_costs(plan)
    return _enforce_budget(plan)

def record_pending_prices(plan: dict[str, Any], db: Any) -> None:
    """把网络/平台/官方抽取价写入待复核库，管理员审核后作为可信价复用。"""
    city = str(plan.get("city") or "")
    if not city:
        return
    approved = {
        (str(p.get("city") or ""), str(p.get("place_name") or ""))
        for p in db.list_place_prices(status="approved")
    }
    seen: set[tuple[str, str]] = set()
    for day in plan.get("days", []) or []:
        for item in list(day.get("attractions", []) or []) + list(day.get("dining", []) or []):
            name = str(item.get("name") or "")
            if not name:
                continue
            price = item.get("fee") or item.get("price") or item.get("budget")
            try:
                price = int(float(price or 0))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            key = (city, name)
            if key in seen or key in approved:
                continue
            level = str(item.get("data_level") or "B")
            source = {
                "A": "官方",
                "B": "平台参考",
                "C": "估算",
                "D": "用户反馈",
            }.get(level, "平台参考")
            url = str(item.get("official_url") or item.get("url") or item.get("map_url") or "")
            note = str(item.get("note") or item.get("price_source") or "")
            db.upsert_place_price(
                name,
                city,
                price,
                source=source,
                source_url=url,
                note=note,
                status="pending",
            )
            seen.add(key)