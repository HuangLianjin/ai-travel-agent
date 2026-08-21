"""天气服务：默认 wttr.in 免 Key，可切换 QWeather/OpenWeather。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

_CITY_CENTERS = {
    "北京": (39.9042, 116.4074),
    "成都": (30.5728, 104.0668),
    "上海": (31.2304, 121.4737),
    "天津": (39.0851, 117.1994),
    "福建": (26.0745, 119.2965),
    "福州": (26.0745, 119.2965),
    "厦门": (24.4798, 118.0894),
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "杭州": (30.2741, 120.1551),
    "西安": (34.3416, 108.9398),
    "重庆": (29.5630, 106.5516),
    "南京": (32.0603, 118.7969),
    "武汉": (30.5928, 114.3055),
    "长沙": (28.2282, 112.9388),
    "青岛": (36.0671, 120.3826),
    "大理": (25.6065, 100.2676),
    "丽江": (26.8721, 100.2299),
    "三亚": (18.2528, 109.5119),
    "桂林": (25.2736, 110.2900),
    "苏州": (31.2989, 120.5853),
    "无锡": (31.4912, 120.3119),
    "宁波": (29.8683, 121.5440),
    "济南": (36.6512, 117.1201),
    "郑州": (34.7466, 113.6254),
    "合肥": (31.8206, 117.2272),
    "南昌": (28.6820, 115.8579),
    "昆明": (25.0389, 102.7183),
    "贵阳": (26.6470, 106.6302),
    "南宁": (22.8170, 108.3665),
    "海口": (20.0440, 110.1999),
    "哈尔滨": (45.8038, 126.5349),
    "长春": (43.8171, 125.3235),
    "沈阳": (41.8057, 123.4315),
    "大连": (38.9140, 121.6147),
    "太原": (37.8706, 112.5489),
    "石家庄": (38.0428, 114.5149),
    "呼和浩特": (40.8424, 111.7490),
    "兰州": (36.0611, 103.8343),
    "西宁": (36.6171, 101.7782),
    "银川": (38.4872, 106.2309),
    "乌鲁木齐": (43.8256, 87.6168),
    "拉萨": (29.6520, 91.1721),
    "珠海": (22.2707, 113.5767),
    "佛山": (23.0218, 113.1219),
    "东莞": (23.0207, 113.7518),
    "泉州": (24.8741, 118.6757),
    "温州": (27.9938, 120.6994),
    "绍兴": (29.9999, 120.5811),
    "洛阳": (34.6197, 112.4540),
    "黄山": (29.7147, 118.3376),
    "张家界": (29.1167, 110.4790),
    "凤凰": (27.9481, 109.5996),
    "敦煌": (40.1421, 94.6619),
    "吐鲁番": (42.9476, 89.1841),
    "喀什": (39.4677, 75.9894),
    "秦皇岛": (39.9354, 119.5997),
    "威海": (37.5131, 122.1204),
    "烟台": (37.4638, 121.4479),
    "徐州": (34.2044, 117.2857),
    "常州": (31.8107, 119.9741),
    "南通": (31.9802, 120.8943),
    "扬州": (32.3942, 119.4127),
    "嘉兴": (30.7461, 120.7555),
    "金华": (29.0792, 119.6474),
    "宜昌": (30.6920, 111.2864),
    "襄阳": (32.0090, 112.1224),
    "岳阳": (29.3570, 113.1290),
    "遵义": (27.7257, 106.9274),
}

_CITY_EN = {
    "北京": "Beijing",
    "成都": "Chengdu",
    "上海": "Shanghai",
    "天津": "Tianjin",
}


class WeatherService:
    def __init__(self) -> None:
        self.provider = os.getenv("WEATHER_PROVIDER", "auto")
        self._location_cache: dict[str, Any] = {}
        self.qweather_key = os.getenv("QWEATHER_API_KEY", "")
        self.qweather_api_host = os.getenv("QWEATHER_API_HOST", "").strip().rstrip("/")
        self.openweather_key = os.getenv("OPENWEATHER_API_KEY", "")

    async def forecast(
        self,
        city: str,
        lat: float | None = None,
        lon: float | None = None,
        start_date: str | None = None,
        days: int = 3,
    ) -> list[dict[str, Any]]:
        if not start_date:
            return []
        if self.provider in ("qweather", "auto") and self.qweather_key and self.qweather_api_host:
            return await self._qweather(city, lat, lon, start_date, days)
        if self.provider in ("openweather", "auto") and self.openweather_key:
            return await self._openweather(city, start_date, days)
        if self.provider in ("openmeteo", "auto"):
            if lat is None or lon is None:
                lat, lon = _CITY_CENTERS.get(city, (0.0, 0.0))
            return await self._open_meteo(lat, lon, start_date, days)
        return await self._wttr(city, lat, lon, start_date, days)

    async def _open_meteo(
        self, lat: float, lon: float, start_date: str, days: int
    ) -> list[dict[str, Any]]:
        codes = {
            0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
            45: "雾", 48: "雾凇", 51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
            56: "冻雨", 57: "冻雨", 61: "小雨", 63: "中雨", 65: "大雨",
            66: "冻雨", 67: "冻雨", 71: "小雪", 73: "中雪", 75: "大雪",
            77: "雪粒", 80: "阵雨", 81: "阵雨", 82: "强阵雨",
            85: "阵雪", 86: "阵雪", 95: "雷阵雨", 96: "雷阵雨伴冰雹",
            99: "雷阵雨伴冰雹",
        }
        start_d = date.fromisoformat(start_date)
        offset = max(0, (start_d - date.today()).days)
        forecast_days = min(16, max(1, offset + days))
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "Asia/Shanghai",
                    "forecast_days": forecast_days,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        daily = data.get("daily", {})
        start = date.fromisoformat(start_date)
        result = []
        for i, day in enumerate(daily.get("time", [])):
            d = date.fromisoformat(day)
            if start <= d < start + timedelta(days=days):
                code = int(daily.get("weathercode", [0])[i])
                result.append(
                    {
                        "date": day,
                        "text": codes.get(code, "多云"),
                        "temp_min": str(daily.get("temperature_2m_min", [""])[i]),
                        "temp_max": str(daily.get("temperature_2m_max", [""])[i]),
                        "humidity": "",
                        "wind": "",
                        "precip": str(daily.get("precipitation_probability_max", [""])[i]),
                    }
                )
        return result

    async def warnings(
        self,
        city: str,
        lat: float | None = None,
        lon: float | None = None,
    ) -> list[dict[str, Any]]:
        if (
            self.provider not in ("qweather", "auto")
            or not self.qweather_key
            or not self.qweather_api_host
        ):
            return []
        async with httpx.AsyncClient(timeout=12) as client:
            lat, lon = await self._qweather_coords(client, city, lat, lon)
            if lat is None or lon is None:
                return []
            resp = await client.get(
                f"https://{self.qweather_api_host}/weatheralert/v1/current/{lat}/{lon}",
                params={"lang": "zh", "localTime": "true"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        alerts = data.get("alerts", [])
        return [
            {
                "title": a.get("headline")
                or (a.get("eventType") or {}).get("name", "")
                or "",
                "text": a.get("description") or a.get("instruction") or "",
                "severity": a.get("severity", ""),
            }
            for a in alerts
        ]

    async def _wttr(
        self,
        city: str,
        lat: float | None,
        lon: float | None,
        start_date: str,
        days: int,
    ) -> list[dict[str, Any]]:
        loc = f"{lat},{lon}" if lat and lon else city
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                f"https://wttr.in/{loc}?format=j1&lang=zh",
                headers={"User-Agent": "TravelAgent/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        start = date.fromisoformat(start_date)
        result: list[dict[str, Any]] = []
        for item in data.get("weather", []):
            d = date.fromisoformat(item["date"])
            if start <= d < start + timedelta(days=days):
                result.append(
                    {
                        "date": item["date"],
                        "text": item.get("hourly", [{}])[0].get("lang_zh", [{}])[0].get("value")
                        or item.get("hourly", [{}])[0].get("weatherDesc", [{}])[0].get("value")
                        or "多云",
                        "temp_min": item.get("mintempC", ""),
                        "temp_max": item.get("maxtempC", ""),
                        "humidity": item.get("avghumidity", ""),
                        "wind": item.get("hourly", [{}])[0].get("windspeedKmph", ""),
                    }
                )
        return result

    async def _qweather(
        self,
        city: str,
        lat: float | None,
        lon: float | None,
        start_date: str,
        days: int,
    ) -> list[dict[str, Any]]:
        start_d = date.fromisoformat(start_date)
        offset = max(0, (start_d - date.today()).days)
        request_days = min(10, max(1, offset + days))
        async with httpx.AsyncClient(timeout=12) as client:
            lat, lon = await self._qweather_coords(client, city, lat, lon)
            if lat is None or lon is None:
                return []
            resp = await client.get(
                f"https://{self.qweather_api_host}/weather/v1/daily/{lat}/{lon}",
                params={"days": request_days, "lang": "zh", "localTime": "true"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        start = date.fromisoformat(start_date)
        result = []
        for item in data.get("days", []):
            day = self._local_day(item.get("forecastStartTime", ""))
            if not day:
                continue
            d = date.fromisoformat(day)
            if start <= d < start + timedelta(days=days):
                daytime = item.get("daytime") or {}
                nighttime = item.get("nighttime") or {}
                condition = daytime.get("condition") or nighttime.get("condition") or {}
                precipitation = daytime.get("precipitation") or {}
                humidity = daytime.get("humidity")
                result.append(
                    {
                        "date": day,
                        "text": condition.get("text", ""),
                        "temp_min": str(
                            (item.get("temperatureMin") or {}).get("value", "")
                        ),
                        "temp_max": str(
                            (item.get("temperatureMax") or {}).get("value", "")
                        ),
                        "humidity": (
                            str(round(humidity * 100))
                            if isinstance(humidity, (int, float))
                            else ""
                        ),
                        "wind": str(
                            ((daytime.get("wind") or {}).get("speed") or {}).get(
                                "value", ""
                            )
                        ),
                        "precip": (
                            str(round(precipitation.get("probability", 0) * 100))
                            if precipitation.get("probability") is not None
                            else ""
                        ),
                    }
                )
        return result

    async def _qweather_coords(
        self,
        client: httpx.AsyncClient,
        city: str,
        lat: float | None = None,
        lon: float | None = None,
    ) -> tuple[float | None, float | None]:
        if lat is not None and lon is not None:
            return float(lat), float(lon)
        cache_key = f"coords:{city}"
        if cache_key in self._location_cache:
            return self._location_cache[cache_key]
        geo = await client.get(
            f"https://{self.qweather_api_host}/geo/v2/city/lookup",
            params={"location": city, "range": "cn", "lang": "zh"},
            headers=self._headers(),
        )
        geo.raise_for_status()
        locations = geo.json().get("location", [])
        if not locations:
            coords = _CITY_CENTERS.get(city)
            if coords:
                self._location_cache[cache_key] = coords
                return coords
            return None, None
        exact = [
            loc
            for loc in locations
            if loc.get("name") == city or loc.get("adm2") == city
        ]
        chosen = exact[0] if exact else locations[0]
        try:
            coords = (float(chosen.get("lat")), float(chosen.get("lon")))
        except (TypeError, ValueError):
            return None, None
        self._location_cache[cache_key] = coords
        return coords

    def _headers(self) -> dict[str, str]:
        return {"X-QW-Api-Key": self.qweather_key}

    def _local_day(self, value: str) -> str:
        if not value:
            return ""
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone(timedelta(hours=8)))
            return dt.date().isoformat()
        except ValueError:
            return value[:10]

    async def _openweather(
        self, city: str, start_date: str, days: int
    ) -> list[dict[str, Any]]:
        q = _CITY_EN.get(city, city)
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={
                    "q": q,
                    "appid": self.openweather_key,
                    "units": "metric",
                    "lang": "zh_cn",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        grouped: dict[str, list[dict]] = {}
        for item in data.get("list", []):
            day = item.get("dt_txt", "")[:10]
            grouped.setdefault(day, []).append(item)
        start = date.fromisoformat(start_date)
        result = []
        for day, items in grouped.items():
            d = date.fromisoformat(day)
            if start <= d < start + timedelta(days=days):
                temps = [float(x.get("main", {}).get("temp", 0)) for x in items]
                result.append(
                    {
                        "date": day,
                        "text": items[0].get("weather", [{}])[0].get("description", ""),
                        "temp_min": str(round(min(temps))) if temps else "",
                        "temp_max": str(round(max(temps))) if temps else "",
                        "humidity": str(items[0].get("main", {}).get("humidity", "")),
                        "wind": str(items[0].get("wind", {}).get("speed", "")),
                    }
                )
        return result


def travel_advice(forecasts: list[dict[str, Any]]) -> str:
    if not forecasts:
        return ""
    rainy = any("雨" in str(f.get("text", "")) for f in forecasts)
    extreme = any(
        _to_float(f.get("temp_max")) >= 35 or _to_float(f.get("temp_min")) <= 0
        for f in forecasts
    )
    if rainy:
        return "未来行程有降雨，建议带伞并预留弹性时间，整体仍可出行。"
    if extreme:
        return "未来行程气温偏高/偏低，建议备好防晒或保暖，出行时间可灵活调整。"
    return "未来天气整体适合出行。"


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
