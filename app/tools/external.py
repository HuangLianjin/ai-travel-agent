"""联网搜索与地图 MCP 统一适配器（可切换真实 API，缺省降级内置语料/地理计算）。"""

from __future__ import annotations

import os
import time
from copy import deepcopy
from typing import Any

from app.corpus import CITIES
from app.observability.metrics import metrics
from app.rag.search import HybridSearcher
from app.tools.geo import estimate_minutes, haversine_km, optimize_route

_SEARCH_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_SEARCH_CACHE_TTL_SECONDS = 24 * 60 * 60
_SEARCH_CACHE_MAX = 200


def _search_cache_get(key: str) -> list[dict[str, Any]] | None:
    item = _SEARCH_CACHE.get(key)
    if not item:
        return None
    ts, results = item
    if time.time() - ts > _SEARCH_CACHE_TTL_SECONDS:
        _SEARCH_CACHE.pop(key, None)
        return None
    return deepcopy(results)


def _search_cache_set(key: str, results: list[dict[str, Any]]) -> None:
    if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
        _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)), None)
    _SEARCH_CACHE[key] = (time.time(), deepcopy(results))


class WebSearchTool:
    """联网搜索：默认 demo 降级到内置语料，配置后可切换 HTTP/MCP 搜索。"""

    def __init__(self, searcher: HybridSearcher | None = None) -> None:
        self.searcher = searcher or HybridSearcher()
        self.mode = os.getenv("WEB_SEARCH_MODE", "demo")
        self.api_url = os.getenv("WEB_SEARCH_API_URL", "")
        self.api_key = os.getenv("WEB_SEARCH_API_KEY", "")
        self.search_provider = os.getenv("SEARCH_PROVIDER", "auto")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY", "")
        self.serpapi_api_key = os.getenv("SERPAPI_API_KEY", "")
        self.bing_search_key = os.getenv("BING_SEARCH_KEY", "")
        self.google_search_key = os.getenv("GOOGLE_SEARCH_KEY", "")
        self.google_cse_id = os.getenv("GOOGLE_CSE_ID", "")
        self.serper_api_key = os.getenv("SERPER_API_KEY", "")
        self.brave_search_key = os.getenv("BRAVE_SEARCH_KEY", "")

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        cache_key = f"{query}|{top_k}"
        cached = _search_cache_get(cache_key)
        if cached is not None:
            metrics.record_tool("search_cache_hit")
            return cached
        metrics.record_tool("search_cache_miss")

        attempts: list[tuple[str, Any]] = []
        if self.search_provider in ("auto", "tavily") and self.tavily_api_key:
            attempts.append(("tavily", self._tavily_search))
        if self.search_provider in ("auto", "serpapi") and self.serpapi_api_key:
            attempts.append(("serpapi", self._serpapi_search))
        if self.search_provider in ("auto", "bing") and self.bing_search_key:
            attempts.append(("bing", self._bing_search))
        if (
            self.search_provider in ("auto", "google")
            and self.google_search_key
            and self.google_cse_id
        ):
            attempts.append(("google", self._google_search))
        if self.search_provider in ("auto", "serper") and self.serper_api_key:
            attempts.append(("serper", self._serper_search))
        if self.search_provider in ("auto", "brave") and self.brave_search_key:
            attempts.append(("brave", self._brave_search))

        for provider, fn in attempts:
            try:
                results = await fn(query, top_k)
                if results:
                    results = self._tag_city(results, query)
                    self._mark_provider(results, provider)
                    metrics.record_tool(f"search_provider_{provider}")
                    _search_cache_set(cache_key, results)
                    return results
            except Exception:
                continue

        if self.mode == "api" and self.api_url:
            try:
                results = await self._api_search(query, top_k)
                if results:
                    results = self._tag_city(results, query)
                    self._mark_provider(results, "custom-api")
                    metrics.record_tool("search_provider_custom_api")
                    _search_cache_set(cache_key, results)
                    return results
            except Exception:
                pass

        results = await self._multi_platform_search(query, top_k)
        if results:
            results = self._tag_city(results, query)
            self._mark_provider(results, "multi-platform")
            metrics.record_tool("search_provider_multi_platform")
            _search_cache_set(cache_key, results)
            return results
        results = self._fallback(query, top_k)
        self._mark_provider(results, "builtin-fallback")
        metrics.record_tool("search_provider_builtin_fallback")
        _search_cache_set(cache_key, results)
        return results

    @staticmethod
    def _mark_provider(
        results: list[dict[str, Any]], provider: str
    ) -> None:
        for item in results:
            item["provider"] = provider

    @staticmethod
    def _tag_city(results: list[dict], query: str) -> list[dict]:
        head = query[:8]
        city = next((c for c in CITIES if c in head), "")
        for item in results:
            if city and not item.get("city"):
                item["city"] = city
        return results

    @staticmethod
    def _normalize_results(
        items: list[tuple[str, str, str]], engine: str, top_k: int
    ) -> list[dict]:
        results = []
        for idx, (url, title, snippet) in enumerate(items[:top_k]):
            if not url or not title:
                continue
            results.append(
                {
                    "id": url,
                    "name": title,
                    "title": title,
                    "url": url,
                    "content": f"{title} {snippet}".strip(),
                    "source": f"{engine} 搜索",
                    "engine": engine,
                    "city": "",
                    "category": "web",
                }
            )
        return results

    async def _tavily_search(self, query: str, top_k: int = 5) -> list[dict]:
        import httpx

        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "max_results": top_k,
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        items = []
        for r in data.get("results", []):
            items.append((r.get("url", ""), r.get("title", ""), r.get("content", "")))
        return self._normalize_results(items, "tavily", top_k)

    async def _serpapi_search(self, query: str, top_k: int = 5) -> list[dict]:
        import httpx

        params = {
            "engine": "google",
            "q": query,
            "api_key": self.serpapi_api_key,
            "num": top_k,
        }
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get("https://serpapi.com/search.json", params=params)
            resp.raise_for_status()
            data = resp.json()
        items = []
        for r in data.get("organic_results", []):
            items.append((r.get("link", ""), r.get("title", ""), r.get("snippet", "")))
        return self._normalize_results(items, "serpapi", top_k)

    async def _bing_search(self, query: str, top_k: int = 5) -> list[dict]:
        import httpx

        headers = {
            "Ocp-Apim-Subscription-Key": self.bing_search_key,
            "User-Agent": "Mozilla/5.0 (compatible; TravelAgent/1.0)",
        }
        params = {"q": query, "count": top_k, "mkt": "zh-CN"}
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                "https://api.bing.microsoft.com/v7.0/search",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        items = []
        for r in data.get("webPages", {}).get("value", []):
            items.append((r.get("url", ""), r.get("name", ""), r.get("snippet", "")))
        return self._normalize_results(items, "bing", top_k)

    async def _google_search(self, query: str, top_k: int = 5) -> list[dict]:
        import httpx

        params = {
            "key": self.google_search_key,
            "cx": self.google_cse_id,
            "q": query,
            "num": top_k,
        }
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        items = [
            (r.get("link", ""), r.get("title", ""), r.get("snippet", ""))
            for r in data.get("items", [])
        ]
        return self._normalize_results(items, "google", top_k)

    async def _serper_search(self, query: str, top_k: int = 5) -> list[dict]:
        import httpx

        headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers=headers,
                json={"q": query, "num": top_k},
            )
            resp.raise_for_status()
            data = resp.json()
        items = [
            (r.get("link", ""), r.get("title", ""), r.get("snippet", ""))
            for r in data.get("organic", [])
        ]
        return self._normalize_results(items, "serper", top_k)

    async def _brave_search(self, query: str, top_k: int = 5) -> list[dict]:
        import httpx

        headers = {
            "X-Subscription-Token": self.brave_search_key,
            "Accept": "application/json",
        }
        params = {"q": query, "count": top_k}
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        items = [
            (r.get("url", ""), r.get("title", ""), r.get("description", ""))
            for r in data.get("web", {}).get("results", [])
        ]
        return self._normalize_results(items, "brave", top_k)

    async def _multi_platform_search(self, query: str, top_k: int) -> list[dict]:
        results: list[dict] = []
        for engine in ("duckduckgo", "bing", "baidu", "sogou", "so360"):
            try:
                results.extend(await self._engine_search(engine, query, top_k // 2 + 1))
            except Exception:
                continue
        unique: dict[str, dict] = {}
        for item in results:
            url = item.get("url")
            if url and url not in unique:
                unique[url] = item
        return list(unique.values())[:top_k]

    async def _engine_search(self, engine: str, query: str, top_k: int) -> list[dict]:
        import re

        import httpx
        from urllib.parse import quote

        urls = {
            "duckduckgo": "https://html.duckduckgo.com/html/?q=",
            "bing": "https://www.bing.com/search?q=",
            "baidu": "https://www.baidu.com/s?wd=",
            "sogou": "https://www.sogou.com/web?query=",
            "so360": "https://www.so.com/s?q=",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=6, follow_redirects=True) as client:
            resp = await client.get(urls[engine] + quote(query), headers=headers)
            resp.raise_for_status()
        html = resp.text
        if engine == "duckduckgo":
            items = re.findall(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                html,
                re.S,
            )
            snippets = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S
            )
        elif engine == "bing":
            items = re.findall(
                r'<li class="b_algo".*?<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                html,
                re.S,
            )
            snippets = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)
        else:
            items = re.findall(
                r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                html,
                re.S,
            )
            snippets = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)
            if engine == "so360":
                snippets = re.findall(
                    r'class="res-list-summary">(.*?)</span>', html, re.S
                )
        if engine == "duckduckgo":
            from urllib.parse import parse_qs, urlparse

            cleaned = []
            for url, title in items:
                if url.startswith("//duckduckgo.com/l/"):
                    parsed = urlparse("https:" + url)
                    url = parse_qs(parsed.query).get("uddg", [url])[0]
                cleaned.append((url, title))
            items = cleaned

        results = []
        for idx, (url, title) in enumerate(items[:top_k]):
            if url.startswith("/"):
                url = "https://www.sogou.com" + url
            snippet = self._strip_html(snippets[idx]) if idx < len(snippets) else ""
            results.append(
                {
                    "id": url,
                    "name": self._strip_html(title),
                    "title": self._strip_html(title),
                    "url": url,
                    "content": f"{self._strip_html(title)} {snippet}".strip(),
                    "source": f"{engine} 搜索",
                    "engine": engine,
                    "city": "",
                    "category": "web",
                }
            )
        return results

    @staticmethod
    def _strip_html(text: str) -> str:
        import re

        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    async def _api_search(self, query: str, top_k: int) -> list[dict]:
        import httpx

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                self.api_url,
                headers=headers,
                json={"query": query, "top_k": top_k},
            )
            resp.raise_for_status()
            return resp.json().get("results", [])

    def _fallback(self, query: str, top_k: int) -> list[dict]:
        results = self.searcher.hybrid_search(query, top_k=top_k)
        for item in results:
            item["engine"] = "builtin-fallback"
            item["url"] = ""
        return results


_GEO_CACHE: dict[str, tuple[float, float]] = {}


class MapMCPTool:
    """地图 MCP：默认降级 Haversine 距离矩阵，配置后可切换高德/Google MCP。"""

    def __init__(self, searcher: HybridSearcher | None = None) -> None:
        self.searcher = searcher or HybridSearcher()
        self.mode = os.getenv("MAP_MCP_MODE", "demo")
        self.api_url = os.getenv("MAP_MCP_URL", "")
        self.api_key = os.getenv("MAP_MCP_API_KEY", "")

    async def geocode_city(self, city: str) -> tuple[float, float] | None:
        if not city:
            return None
        if city in _GEO_CACHE:
            return _GEO_CACHE[city]
        if self.mode != "amap" or not self.api_key:
            return None
        import httpx

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    "https://restapi.amap.com/v3/geocode/geo",
                    params={"address": city, "key": self.api_key},
                )
                resp.raise_for_status()
                data = resp.json()
            geocodes = data.get("geocodes") or []
            if not geocodes:
                return None
            loc = geocodes[0].get("location") or ""
            lon, lat = (float(x) for x in loc.split(","))
            _GEO_CACHE[city] = (lat, lon)
            return lat, lon
        except Exception:
            return None

    async def route(self, origin: dict, destination: dict) -> dict:
        if self.mode == "amap" and self.api_key:
            return await self._amap_route(origin, destination)
        if self.mode == "api" and self.api_url:
            return await self._api_route(origin, destination)
        return {
            "engine": "haversine-fallback",
            "distance_km": round(
                haversine_km(
                    float(origin.get("lat", 0)),
                    float(origin.get("lon", 0)),
                    float(destination.get("lat", 0)),
                    float(destination.get("lon", 0)),
                ),
                1,
            ),
            "cost_yuan": None,
            "minutes": estimate_minutes(
                float(origin.get("lat", 0)),
                float(origin.get("lon", 0)),
                float(destination.get("lat", 0)),
                float(destination.get("lon", 0)),
            ),
            "mode": "mixed",
        }

    async def distance_matrix(
        self, points: list[dict], preference: str = "auto"
    ) -> list[dict]:
        if not points:
            return []
        ordered = optimize_route(points)
        legs = []
        for i in range(len(ordered) - 1):
            leg = await self.smart_route(
                ordered[i], ordered[i + 1], preference=preference
            )
            legs.append(
                {
                    "from": ordered[i].get("name"),
                    "to": ordered[i + 1].get("name"),
                    **leg,
                    "advice": self._mode_advice(leg),
                }
            )
        return legs

    @staticmethod
    def _mode_advice(leg: dict) -> str:
        distance = leg.get("distance_km") or 0
        mode = leg.get("mode", "公共交通")
        if mode in ("共享单车", "骑行"):
            return "距离较短，建议骑行或共享单车，低碳省时"
        if mode in ("打车", "驾车"):
            return f"距离约 {distance} 公里，打车/驾车更省时"
        return f"距离约 {distance} 公里，建议公共交通"

    async def smart_route(
        self, origin: dict, destination: dict, preference: str = "auto"
    ) -> dict:
        if self.mode == "amap" and self.api_key:
            return await self._amap_smart(origin, destination, preference)
        return await self.route(origin, destination)

    async def _amap_smart(
        self, origin: dict, destination: dict, preference: str
    ) -> dict:
        city = (
            origin.get("city")
            or destination.get("city")
            or os.getenv("MAP_MCP_CITY", "")
        )
        options: list[dict] = []
        if city:
            try:
                transit = await self._amap_transit(origin, destination, city)
                if transit:
                    options.append(transit)
            except Exception:
                pass
        try:
            driving = await self._amap_driving(origin, destination)
            if driving:
                taxi = dict(driving)
                taxi["mode"] = "打车"
                taxi["engine"] = "amap-taxi-estimate"
                taxi["cost_yuan"] = round(
                    13 + max(0, taxi.get("distance_km", 0) - 3) * 2.3
                )
                options.append(taxi)
        except Exception:
            pass
        distance = min((o.get("distance_km", 99) for o in options), default=99)
        if distance <= 5:
            options.append(
                {
                    "engine": "bike-estimate",
                    "distance_km": round(distance, 1),
                    "minutes": max(3, round(distance / 15 * 60)),
                    "mode": "共享单车",
                    "cost_yuan": 2.5,
                }
            )
        if not options:
            return await self.route(origin, destination)
        return self._pick_mode(options, preference)

    @staticmethod
    def _pick_mode(options: list[dict], preference: str) -> dict:
        pref = preference or "auto"
        if any(k in pref for k in ("打车", "出租车", "自驾", "驾车")):
            return MapMCPTool._best(options, ("打车", "驾车"))
        if any(k in pref for k in ("公交", "地铁", "公共交通")):
            return MapMCPTool._best(options, ("公共交通",))
        if any(k in pref for k in ("共享", "骑行", "自行车")):
            return MapMCPTool._best(options, ("共享单车",))
        bike = next((o for o in options if o.get("mode") == "共享单车"), None)
        transit = next((o for o in options if o.get("mode") == "公共交通"), None)
        taxi = next((o for o in options if o.get("mode") == "打车"), None)
        distances = [o.get("distance_km") for o in options if o.get("distance_km")]
        distance = min(distances) if distances else None
        if distance is not None and distance <= 2.5 and bike:
            return bike
        if distance is not None and distance <= 10 and transit:
            return transit
        if taxi and (not transit or taxi.get("minutes", 99) <= transit.get("minutes", 99) * 0.75):
            return taxi
        if transit:
            return transit
        if bike:
            return bike
        return options[0]

    @staticmethod
    def _best(options: list[dict], modes: tuple[str, ...]) -> dict:
        matched = [o for o in options if o.get("mode") in modes]
        if not matched:
            return options[0]
        return min(matched, key=lambda o: (o.get("minutes", 999), o.get("cost_yuan", 0)))

    async def search_poi(self, query: str, top_k: int = 5) -> list[dict]:
        return self.searcher.hybrid_search(query, top_k=top_k)

    async def poi_list(
        self, query: str, city: str = "", count: int = 5
    ) -> list[dict]:
        from app.observability.metrics import metrics

        metrics.record_tool("amap_poi")
        if self.mode != "amap" or not self.api_key:
            return []
        try:
            import httpx

            params = {
                "key": self.api_key,
                "keywords": query,
                "city": city,
                "offset": count,
                "extensions": "all",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://restapi.amap.com/v3/place/text", params=params
                )
                resp.raise_for_status()
                data = resp.json()
            pois = data.get("pois") or []
            results = []
            for poi in pois[:count]:
                location = str(poi.get("location", ""))
                lat = lon = ""
                if "," in location:
                    lon, lat = location.split(",", 1)
                biz = poi.get("biz_ext") or {}
                results.append(
                    {
                        "name": poi.get("name", ""),
                        "address": poi.get("address")
                        or f"{poi.get('pname', '')}{poi.get('cityname', '')}{poi.get('adname', '')}",
                        "lat": lat,
                        "lon": lon,
                        "cost": biz.get("cost") or poi.get("cost"),
                        "rating": biz.get("rating") or poi.get("rating"),
                        "type": poi.get("type", ""),
                    }
                )
            return results
        except Exception:
            return []

    async def poi_detail(self, query: str, city: str = "") -> dict | None:
        if self.mode != "amap" or not self.api_key:
            return None
        try:
            import httpx

            params = {
                "key": self.api_key,
                "keywords": query,
                "city": city,
                "offset": 1,
                "extensions": "all",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://restapi.amap.com/v3/place/text", params=params
                )
                resp.raise_for_status()
                data = resp.json()
            pois = data.get("pois") or []
            if not pois:
                return None
            poi = pois[0]
            location = str(poi.get("location", ""))
            lat = lon = ""
            if "," in location:
                lon, lat = location.split(",", 1)
            biz = poi.get("biz_ext") or {}
            return {
                "name": poi.get("name", ""),
                "address": poi.get("address")
                or f"{poi.get('pname', '')}{poi.get('cityname', '')}{poi.get('adname', '')}",
                "lat": lat,
                "lon": lon,
                "cost": biz.get("cost") or poi.get("cost"),
                "rating": biz.get("rating") or poi.get("rating"),
            }
        except Exception:
            return None

    async def _amap_route(self, origin: dict, destination: dict) -> dict:
        city = (
            origin.get("city")
            or destination.get("city")
            or os.getenv("MAP_MCP_CITY", "")
        )
        if city:
            return await self._amap_transit(origin, destination, city)
        return await self._amap_driving(origin, destination)

    async def _amap_transit(
        self, origin: dict, destination: dict, city: str
    ) -> dict:
        import httpx

        params = {
            "key": self.api_key,
            "origin": f"{origin.get('lon', 0)},{origin.get('lat', 0)}",
            "destination": f"{destination.get('lon', 0)},{destination.get('lat', 0)}",
            "city": city,
            "cityd": city,
            "extensions": "all",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://restapi.amap.com/v3/direction/transit/integrated",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("status") != "1":
            raise RuntimeError(f"高德公交 API 返回失败：{data.get('info', 'unknown')}")
        transit = (data.get("route", {}).get("transits") or [{}])[0]
        distance = int(transit.get("distance", 0) or 0)
        duration = int(transit.get("duration", 0) or 0)
        steps = []
        for seg in transit.get("segments", []) or []:
            bus = seg.get("bus") or {}
            buslines = bus.get("buslines") or []
            if buslines:
                bl = buslines[0]
                dep = (bl.get("departure_stop") or {}).get("name") or ""
                arr = (bl.get("arrival_stop") or {}).get("name") or ""
                label = f"乘坐{bl.get('name') or '公交'}"
                if dep and arr:
                    label += f"：{dep} → {arr}"
                steps.append(label)
            else:
                railway = seg.get("railway") or {}
                lines = railway.get("lines") or []
                if lines:
                    ln = lines[0]
                    dep = (ln.get("departure_stop") or {}).get("name") or ""
                    arr = (ln.get("arrival_stop") or {}).get("name") or ""
                    label = f"乘坐{ln.get('name') or '地铁'}"
                    if dep and arr:
                        label += f"：{dep} → {arr}"
                    steps.append(label)
                elif seg.get("walking"):
                    steps.append("步行接驳")
        return {
            "engine": "amap-transit",
            "distance_km": round(distance / 1000, 1),
            "minutes": max(1, round(duration / 60)),
            "mode": "公共交通",
            "cost_yuan": max(0, round(float(transit.get("cost", 0) or 0))),
            "transit_steps": steps[:4],
        }

    async def _amap_driving(self, origin: dict, destination: dict) -> dict:
        import httpx

        params = {
            "key": self.api_key,
            "origin": f"{origin.get('lon', 0)},{origin.get('lat', 0)}",
            "destination": f"{destination.get('lon', 0)},{destination.get('lat', 0)}",
            "extensions": "all",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://restapi.amap.com/v3/direction/driving",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("status") != "1":
            raise RuntimeError(f"高德驾车 API 返回失败：{data.get('info', 'unknown')}")
        path = (data.get("route", {}).get("paths") or [{}])[0]
        distance = int(path.get("distance", 0) or 0)
        duration = int(path.get("duration", 0) or 0)
        return {
            "engine": "amap-driving",
            "distance_km": round(distance / 1000, 1),
            "minutes": max(1, round(duration / 60)),
            "mode": "驾车",
            "cost_yuan": max(0, round(float(path.get("tolls", 0) or 0))),
        }

    async def _api_route(self, origin: dict, destination: dict) -> dict:
        import httpx

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                self.api_url,
                headers=headers,
                json={"origin": origin, "destination": destination},
            )
            resp.raise_for_status()
            return resp.json()

