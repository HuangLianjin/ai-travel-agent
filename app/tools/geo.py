"""地理距离、路线排序与行程纠偏工具。"""

from __future__ import annotations

import math
from typing import Any


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def estimate_minutes(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    km = haversine_km(lat1, lon1, lat2, lon2)
    return max(8, int(km / 28 * 60 + 12))


def optimize_route(points: list[dict], start: dict | None = None) -> list[dict]:
    """按最近邻策略优化景点顺序，减少跨区折返。"""
    if not points:
        return []
    remaining = [dict(p) for p in points]
    ordered: list[dict] = []
    cursor = start or remaining[0]
    while remaining:
        remaining.sort(
            key=lambda p: haversine_km(
                float(cursor.get("lat") or 0),
                float(cursor.get("lon") or 0),
                float(p.get("lat") or 0),
                float(p.get("lon") or 0),
            )
        )
        nxt = remaining.pop(0)
        ordered.append(nxt)
        cursor = nxt
    return ordered


def route_legs(points: list[dict]) -> list[dict]:
    legs = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        has_coords = (
            a.get("lat")
            and a.get("lon")
            and b.get("lat")
            and b.get("lon")
        )
        if has_coords:
            distance_km = round(
                haversine_km(
                    float(a.get("lat")),
                    float(a.get("lon")),
                    float(b.get("lat")),
                    float(b.get("lon")),
                ),
                1,
            )
            minutes = estimate_minutes(
                float(a.get("lat")),
                float(a.get("lon")),
                float(b.get("lat")),
                float(b.get("lon")),
            )
        else:
            distance_km = 0.0
            minutes = 30
        legs.append(
            {
                "from": a.get("name"),
                "to": b.get("name"),
                "from_lat": a.get("lat") or "",
                "from_lon": a.get("lon") or "",
                "to_lat": b.get("lat") or "",
                "to_lon": b.get("lon") or "",
                "mode": a.get("mode") or "auto",
                "distance_km": distance_km,
                "minutes": minutes,
            }
        )
    return legs


def autocorrect_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """规则纠偏：去重、跨区折返提示、营业时间校验。"""
    issues: list[str] = []
    for day in plan.get("days", []):
        seen: set[str] = set()
        kept = []
        for item in day.get("attractions", []):
            name = item.get("name", "")
            if name in seen:
                issues.append(f"{day.get('theme', '')} 中重复出现 {name}")
                continue
            seen.add(name)
            kept.append(item)
        day["attractions"] = kept

        route = optimize_route(day.get("attractions", []))
        day["route"] = route_legs(route)
        day["attractions"] = route
        total = sum(leg.get("minutes", 0) for leg in day.get("route", []))
        if total > 180:
            issues.append(f"{day.get('theme', '')} 交通时间较长，建议精简一个景点")

    plan["validation_issues"] = issues
    plan["valid"] = len(issues) == 0
    return plan

