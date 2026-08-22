"""真实业务数据接入层：票务/餐厅/酒店/打车/共享单车，按需调用外部 API。"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from datetime import date, timedelta
from typing import Any

import httpx

from app.llm import get_llm
from app.tools.external import MapMCPTool, WebSearchTool

_TICKET_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TICKET_CACHE_TTL_SECONDS = 24 * 60 * 60

_RESTAURANT_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_RESTAURANT_CACHE_TTL_SECONDS = 24 * 60 * 60

_HOTEL_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_HOTEL_CACHE_TTL_SECONDS = 24 * 60 * 60


def _has_cjk(name: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(name or ""))


def display_hotel_name(name: str) -> str:
    """中英混合名只保留中文部分，避免回复文本里出现英文酒店名。"""
    text = str(name or "")
    for i, ch in enumerate(text):
        if "\u4e00" <= ch <= "\u9fff":
            return text[i:]
    return text


class LiveDataService:
    def __init__(self) -> None:
        self.ticket_url = os.getenv("TICKET_API_URL", "")
        self.ticket_key = os.getenv("TICKET_API_KEY", "")
        self.restaurant_url = os.getenv("RESTAURANT_API_URL", "")
        self.restaurant_key = os.getenv("RESTAURANT_API_KEY", "")
        self.hotel_url = os.getenv("HOTEL_API_URL", "")
        self.hotel_key = os.getenv("HOTEL_API_KEY", "")
        self.hotel_provider = os.getenv("HOTEL_PROVIDER", "auto")
        self.booking_rapidapi_key = os.getenv("BOOKING_RAPIDAPI_KEY", "")
        self.booking_rapidapi_host = os.getenv(
            "BOOKING_RAPIDAPI_HOST", "booking-com.p.rapidapi.com"
        )
        self.taxi_url = os.getenv("TAXI_API_URL", "")
        self.taxi_key = os.getenv("TAXI_API_KEY", "")
        self.bike_url = os.getenv("BIKE_API_URL", "")
        self.bike_key = os.getenv("BIKE_API_KEY", "")
        self.map_mcp = MapMCPTool()
        self.web_search = WebSearchTool()
        self.llm = get_llm()

    async def enrich_plan(
        self, plan: dict[str, Any], departure_date: str = ""
    ) -> dict[str, Any]:
        city = str(plan.get("city") or "")
        days = plan.get("days") or []
        travelers = max(
            1, int((plan.get("params") or {}).get("travelers", 2) or 2)
        )
        nights = max(0, len(days) - 1)
        tasks: list[asyncio.Task[None]] = []
        for day in days:
            for item in day.get("attractions", []):
                tasks.append(
                    asyncio.create_task(
                        self._enrich_ticket(item, city, departure_date)
                    )
                )
            for item in day.get("dining", []):
                tasks.append(
                    asyncio.create_task(self._enrich_restaurant(item, city))
                )
        hotel_task = asyncio.create_task(
            self._hotels(city, departure_date, nights, travelers)
        )
        if tasks:
            await asyncio.gather(*tasks)
        plan["hotel_options"] = await hotel_task
        for day in days:
            self._sync_timeline(day)
        if plan["hotel_options"]:
            cheapest = min(
                plan["hotel_options"],
                key=lambda h: (
                    h.get("price")
                    if isinstance(h.get("price"), (int, float))
                    else 10**9
                ),
            )
            price = cheapest.get("price")
            if isinstance(price, (int, float)) and nights > 0:
                plan["hotel"] = {
                    **cheapest,
                    "price_per_night": int(price),
                    "nights": nights,
                    "total_price": int(price) * nights,
                    "room_type": cheapest.get("room_type", "大床房"),
                    "source": "Booking.com RapidAPI",
                }
        return plan


    @staticmethod
    def _sync_timeline(day: dict[str, Any]) -> None:
        """把景点/餐饮的实时价格同步到时间线条目，保证页面展示一致。"""
        by_name: dict[str, list[dict[str, Any]]] = {}
        for attr in day.get("attractions", []) or []:
            by_name.setdefault(str(attr.get("name") or ""), []).append(attr)
        for food in day.get("dining", []) or []:
            by_name.setdefault(str(food.get("name") or ""), []).append(food)
        for item in day.get("timeline", []) or []:
            key = str(item.get("title") or item.get("restaurant") or "")
            matches = by_name.get(key) or []
            if not matches:
                continue
            src = matches[0]
            if item.get("type") == "attraction":
                item["price"] = src.get("fee") or src.get("price") or 0
            elif item.get("type") == "food":
                item["price"] = src.get("price") or src.get("fee") or 0
            for field in (
                "price_source",
                "data_level",
                "data_label",
                "address",
                "official_url",
            ):
                if src.get(field):
                    item[field] = src[field]

    async def _translate_hotel_names(
        self, names: list[str], city: str
    ) -> dict[str, str]:
        if not names or self.llm.settings.llm_mode != "openai":
            return {}
        system = (
            "你是酒店名翻译器。把英文酒店名翻译成简洁、符合中文习惯的名称，"
            "不要加引号和解释。只输出 JSON，格式 {\"0\": \"中文名\", \"1\": \"中文名\"}。"
        )
        lines = "\n".join(f"{i}. {name}" for i, name in enumerate(names))
        try:
            content = await self.llm.complete(system, f"城市：{city}\n{lines}")
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                return {}
            data = json.loads(match.group(0))
            result: dict[str, str] = {}
            for i, name in enumerate(names):
                zh = data.get(str(i))
                if zh and isinstance(zh, str):
                    result[name] = zh.strip()
            return result
        except Exception:
            return {}
    async def _enrich_ticket(
        self, item: dict[str, Any], city: str, departure_date: str
    ) -> None:
        name = str(item.get("name") or "")
        if not name:
            return
        if item.get("fee") and str(item.get("price_source") or "") not in ("", "估算价"):
            return
        if self.ticket_url:
            data = await self._call(
                self.ticket_url,
                self.ticket_key,
                {"name": name, "city": city, "date": departure_date},
            )
            if data:
                self._apply_ticket(item, data)
                return
        ticket = await self._ticket_from_web(name, city)
        if ticket:
            self._apply_ticket(item, ticket)

    @staticmethod
    def _apply_ticket(item: dict[str, Any], data: dict[str, Any]) -> None:
        if data.get("fee") is not None:
            try:
                item["fee"] = int(float(data["fee"]))
            except (TypeError, ValueError):
                pass
        if data.get("opening_hours"):
            item["opening_hours"] = data["opening_hours"]
        if data.get("available") is not None:
            item["available"] = data["available"]
        if data.get("note"):
            item["note"] = data["note"]
        url = data.get("official_url") or data.get("source_url")
        if url:
            item["official_url"] = url
        if data.get("fee") is not None:
            url = str(data.get("official_url") or data.get("source_url") or "")
            level, label = "B", "平台参考价"
            if any(k in url for k in (".gov.cn", "mct.gov.cn")):
                level, label = "A", "官方价格"
            elif any(
                k in url
                for k in (
                    "trip.com",
                    "ctrip",
                    "qunar",
                    "mafengwo",
                    "qyer",
                    "meituan",
                    "dianping",
                    "booking.com",
                    "zhihu",
                    "baike.baidu",
                    "sina",
                    "sohu",
                    "qq.com",
                )
            ):
                level, label = "B", "平台参考价"
            item["price_source"] = data.get("price_source") or label
            item["data_level"] = level
            item["data_label"] = label

    async def _ticket_from_web(
        self, name: str, city: str
    ) -> dict[str, Any] | None:
        key = f"{city}|{name}"
        cached = _TICKET_CACHE.get(key)
        if cached and time.time() - cached[0] < _TICKET_CACHE_TTL_SECONDS:
            return cached[1]
        query = f"{name} {city} 门票价格 官方 预约"
        try:
            results = await self.web_search.search(query, top_k=5)
        except Exception:
            results = []
        snippets = [
            str(r.get("content") or r.get("snippet") or "")
            for r in results
        ]
        urls = [str(r.get("url") or "") for r in results if r.get("url")]
        text = "\n".join(snippets)[:3000]
        parsed: dict[str, Any] = {}
        if text and self.llm.settings.llm_mode == "openai":
            parsed = await self._llm_extract_ticket(name, city, text)
        if parsed.get("fee") is None:
            fee = self._regex_ticket_price(text)
            if fee:
                parsed["fee"] = fee
        if parsed.get("fee") is None:
            return None
        if not parsed.get("official_url") and urls:
            parsed["official_url"] = urls[0]
        parsed.setdefault("price_source", "网络参考价")
        _TICKET_CACHE[key] = (time.time(), parsed)
        return parsed

    async def _llm_extract_ticket(
        self, name: str, city: str, text: str
    ) -> dict[str, Any]:
        system = (
            "你是景区票务信息抽取器，只根据给定搜索结果抽取事实，禁止编造。"
            "只输出 JSON，格式："
            '{"fee": 数字或null, "opening_hours": "开放时间", '
            '"official_url": "官方/权威来源", "note": "一句话说明", "available": true}'
        )
        user = f"景点：{name}\n城市：{city}\n搜索结果：\n{text}"
        try:
            content = await self.llm.complete(system, user)
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                return {}
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _regex_ticket_price(text: str) -> int | None:
        match = re.search(
            r"(?:门票|票价|成人票)[:：]?\s*¥\s*(\d{1,4})", text
        )
        if not match:
            match = re.search(
                r"(?:门票|票价|成人票)[:：]?\s*(\d{1,4})\s*元", text
            )
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    async def _enrich_restaurant(
        self, item: dict[str, Any], city: str
    ) -> None:
        name = str(item.get("name") or "")
        if not name:
            return
        if self.restaurant_url:
            data = await self._call(
                self.restaurant_url,
                self.restaurant_key,
                {"name": name, "city": city},
            )
            if data:
                if data.get("price") is not None:
                    item["price"] = data["price"]
                if data.get("status"):
                    item["status"] = data["status"]
                if data.get("note"):
                    item["note"] = data["note"]
                item["price_source"] = "餐厅API"
        source = str(item.get("price_source") or "")
        has_address = bool(item.get("address"))
        has_price = item.get("price") is not None and "估算" not in source
        if has_address and has_price and "高德" in source:
            return
        cache_key = f"{city}|{name}"
        cached = _RESTAURANT_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < _RESTAURANT_CACHE_TTL_SECONDS:
            poi = cached[1]
        else:
            poi = await self.map_mcp.poi_detail(f"{city} {name}", city)
            _RESTAURANT_CACHE[cache_key] = (time.time(), poi)
        if not poi:
            return
        if not item.get("address"):
            item["address"] = poi.get("address", "")
        if not item.get("lat"):
            item["lat"] = poi.get("lat", "")
        if not item.get("lon"):
            item["lon"] = poi.get("lon", "")
        if poi.get("cost"):
            try:
                cost = int(float(poi["cost"]))
                if cost > 0:
                    item["price"] = cost
                    item["price_source"] = "高德人均参考"
                    item["data_level"] = "B"
                    item["data_label"] = "参考价"
            except (TypeError, ValueError):
                pass

    async def _hotels(
        self,
        city: str,
        departure_date: str,
        nights: int,
        travelers: int,
    ) -> list[dict[str, Any]]:
        if nights <= 0 or not city:
            return []
        cache_key = f"{city}|{departure_date}|{nights}|{travelers}|{self.hotel_provider}"
        cached = _HOTEL_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < _HOTEL_CACHE_TTL_SECONDS:
            return cached[1]
        if self.hotel_provider in ("booking", "auto") and self.booking_rapidapi_key:
            hotels = await self._hotels_booking(
                city, departure_date, nights, travelers
            )
        elif self.hotel_url:
            data = await self._call(
                self.hotel_url,
                self.hotel_key,
                {"city": city, "check_in": departure_date, "nights": nights},
            )
            hotels = data.get("hotels", []) if isinstance(data, dict) else []
        else:
            hotels = []
        _HOTEL_CACHE[cache_key] = (time.time(), hotels)
        return hotels

    async def _call(
        self, url: str, key: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        try:
            headers = {}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, headers=headers, json=params)
                resp.raise_for_status()
                data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def _hotels_booking(
        self,
        city: str,
        date_str: str,
        nights: int,
        travelers: int,
    ) -> list[dict[str, Any]]:
        """Booking.com RapidAPI：城市搜索 + 真实房价，按晚数与房型返回。"""
        if not self.booking_rapidapi_key:
            return []
        headers = {
            "X-RapidAPI-Key": self.booking_rapidapi_key,
            "X-RapidAPI-Host": self.booking_rapidapi_host,
        }
        rooms = max(1, math.ceil(travelers / 2))
        try:
            arrival = date.fromisoformat(date_str or "")
        except ValueError:
            arrival = date.today()
        departure = arrival + timedelta(days=nights)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                loc_resp = await client.get(
                    f"https://{self.booking_rapidapi_host}/v1/hotels/locations",
                    params={"name": city, "locale": "zh-cn"},
                    headers=headers,
                )
                loc_resp.raise_for_status()
                locations = loc_resp.json()
                if not isinstance(locations, list) or not locations:
                    return []
                dest = next(
                    (
                        x
                        for x in locations
                        if x.get("dest_type") in ("CITY", "REGION", "COUNTRY")
                    ),
                    locations[0],
                )
                dest_id = dest.get("dest_id") or dest.get("id")
                dest_type = dest.get("dest_type") or "CITY"
                if not dest_id:
                    return []

                search_resp = await client.get(
                    f"https://{self.booking_rapidapi_host}/v1/hotels/search",
                    params={
                        "dest_id": dest_id,
                        "dest_type": dest_type,
                        "locale": "zh-cn",
                        "filter_by_currency": "CNY",
                        "order_by": "price",
                        "checkin_date": arrival.isoformat(),
                        "checkout_date": departure.isoformat(),
                        "room_number": str(rooms),
                        "adults_number": "2",
                        "units": "metric",
                    },
                    headers=headers,
                )
                search_resp.raise_for_status()
                data = search_resp.json()
        except Exception:
            return []

        results = []
        hotels = data.get("result", []) if isinstance(data, dict) else []
        hotels = [h for h in hotels if h.get("hotel_name") or h.get("name")]
        room_type = "双床房" if travelers >= 2 else "大床房"
        if rooms > 1:
            room_type = f"双床房 x {rooms}"
        for h in hotels[:5]:
            price_breakdown = h.get("price_breakdown") or {}
            price = (
                h.get("min_total_price")
                or price_breakdown.get("gross_price")
                or price_breakdown.get("all_inclusive_price")
                or h.get("price")
            )
            if not isinstance(price, (int, float)):
                price = None
            else:
                price = int(round(price))
            results.append(
                {
                    "name": h.get("hotel_name") or h.get("name") or "",
                    "stars": h.get("class") or h.get("stars") or 0,
                    "review_score": h.get("review_score")
                    or h.get("reviewScore")
                    or "",
                    "review_count": h.get("review_nr") or h.get("reviewCount") or 0,
                    "price": price,
                    "price_per_night": price,
                    "nights": nights,
                    "room_type": room_type,
                    "currency": h.get("currencycode") or "CNY",
                    "distance_km": h.get("distance_to_cc") or h.get("distance") or "",
                    "lat": h.get("latitude") or h.get("lat") or "",
                    "lon": h.get("longitude") or h.get("lon") or "",
                    "url": h.get("url")
                    or f"https://www.booking.com/searchresults.zh-cn.html?ss={city}",
                    "source": "Booking.com RapidAPI",
                }
            )
        english_names = [
            h.get("name", "") for h in results if not _has_cjk(h.get("name"))
        ]
        translated = await self._translate_hotel_names(english_names, city)
        for h in results:
            if not _has_cjk(h.get("name")):
                zh = translated.get(h.get("name", "")) or ""
                if zh:
                    h["display_name"] = zh
            if not h.get("display_name") and _has_cjk(h.get("name")):
                h["display_name"] = display_hotel_name(h.get("name"))
        chinese = [
            h
            for h in results
            if _has_cjk(h.get("name") or h.get("display_name"))
        ]
        english = [
            h
            for h in results
            if not _has_cjk(h.get("name") or h.get("display_name"))
        ]
        chinese.sort(
            key=lambda h: h.get("price")
            if isinstance(h.get("price"), (int, float))
            else 10**9
        )
        english.sort(
            key=lambda h: h.get("price")
            if isinstance(h.get("price"), (int, float))
            else 10**9
        )
        if len(chinese) >= 3:
            return chinese[:5]
        return chinese + english