"""真实业务数据接入层：票务/餐厅/酒店/打车/共享单车，按需调用外部 API。"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import httpx


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

    async def enrich_plan(
        self, plan: dict[str, Any], departure_date: str = ""
    ) -> dict[str, Any]:
        for day in plan.get("days", []):
            for item in day.get("attractions", []):
                await self._enrich_ticket(item, plan.get("city", ""), departure_date)
            for item in day.get("dining", []):
                await self._enrich_restaurant(item, plan.get("city", ""))
        plan["hotel_options"] = await self._hotels(
            plan.get("city", ""), departure_date
        )
        return plan

    async def _enrich_ticket(
        self, item: dict[str, Any], city: str, date: str
    ) -> None:
        if not self.ticket_url:
            return
        data = await self._call(
            self.ticket_url,
            self.ticket_key,
            {"name": item.get("name", ""), "city": city, "date": date},
        )
        if not data:
            return
        if data.get("fee") is not None:
            item["fee"] = data["fee"]
        if data.get("opening_hours"):
            item["opening_hours"] = data["opening_hours"]
        if data.get("available") is not None:
            item["available"] = data["available"]
        if data.get("note"):
            item["note"] = data["note"]
        item["price_source"] = "票务API"

    async def _enrich_restaurant(
        self, item: dict[str, Any], city: str
    ) -> None:
        if not self.restaurant_url:
            return
        data = await self._call(
            self.restaurant_url,
            self.restaurant_key,
            {"name": item.get("name", ""), "city": city},
        )
        if not data:
            return
        if data.get("price") is not None:
            item["price"] = data["price"]
        if data.get("status"):
            item["status"] = data["status"]
        if data.get("note"):
            item["note"] = data["note"]
        item["price_source"] = "餐厅API"

    async def _hotels(self, city: str, date: str) -> list[dict[str, Any]]:
        if self.hotel_provider in ("booking", "auto") and self.booking_rapidapi_key:
            return await self._hotels_booking(city, date)
        if not self.hotel_url:
            return []
        data = await self._call(
            self.hotel_url,
            self.hotel_key,
            {"city": city, "check_in": date, "nights": 1},
        )
        return data.get("hotels", []) if isinstance(data, dict) else []

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
        self, city: str, date_str: str
    ) -> list[dict[str, Any]]:
        """Booking.com RapidAPI：城市搜索 + 当日真实房价。"""
        if not self.booking_rapidapi_key:
            return []
        headers = {
            "X-RapidAPI-Key": self.booking_rapidapi_key,
            "X-RapidAPI-Host": self.booking_rapidapi_host,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
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

                try:
                    arrival = date.fromisoformat(date_str or "")
                except ValueError:
                    arrival = date.today()
                departure = arrival + timedelta(days=1)
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
                        "room_number": "1",
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
            results.append(
                {
                    "name": h.get("hotel_name") or h.get("name") or "",
                    "stars": h.get("class") or h.get("stars") or 0,
                    "review_score": h.get("review_score")
                    or h.get("reviewScore")
                    or "",
                    "review_count": h.get("review_nr") or h.get("reviewCount") or 0,
                    "price": price,
                    "currency": h.get("currencycode") or "CNY",
                    "distance_km": h.get("distance_to_cc") or h.get("distance") or "",
                    "lat": h.get("latitude") or h.get("lat") or "",
                    "lon": h.get("longitude") or h.get("lon") or "",
                    "url": h.get("url")
                    or f"https://www.booking.com/searchresults.zh-cn.html?ss={city}",
                    "source": "Booking.com RapidAPI",
                }
            )
        return results
