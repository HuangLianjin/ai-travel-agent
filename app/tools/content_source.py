"""公开内容源适配器：通过搜索接口发现攻略/景点/美食页面并提取正文。

设计原则：
- 不破解反爬、不绕过登录风控；
- 默认关闭，通过 CONTENT_SOURCE_ENABLED=true 开启；
- 搜索结果必须保留来源 URL，便于溯源与人工复核。
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from copy import deepcopy
from html import unescape
from typing import Any

import httpx

from app.tools.external import WebSearchTool
from app.tools.weather import _CITY_CENTERS as CITY_CENTERS

_PAGE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PAGE_CACHE_TTL = 24 * 60 * 60
_PAGE_CACHE_MAX = 200

_CHARSET_RE = re.compile(r'''charset\s*=\s*["']?([\w-]+)''', re.I)

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}


def _extract_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<(nav|header|footer|aside).*?>.*?</\1>", " ", html)
    html = re.sub(r"<br\s*/?>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", "\n", html)
    html = html.replace("&nbsp;", " ")
    lines = []
    for raw in html.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) >= 4:
            lines.append(line)
    return "\n".join(lines)[:6000]


def _decode_response(resp: httpx.Response) -> str:
    raw = resp.content
    charset = ""
    content_type = resp.headers.get("content-type", "")
    m = _CHARSET_RE.search(content_type)
    if m:
        charset = m.group(1).lower()
    if not charset:
        head = raw[:2048].decode("utf-8", "ignore")
        m = _CHARSET_RE.search(head)
        if m:
            charset = m.group(1).lower()
    for encoding in (charset, "utf-8", "gb18030"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "ignore")


def _meta_description(html: str) -> str:
    patterns = [
        r'''<meta[^>]+(?:name|property)=["'](?:description|og:description)["'][^>]+content=["']([^"']+)''',
        r'''<meta[^>]+content=["']([^"']+)["'][^>]+(?:name|property)=["'](?:description|og:description)["']''',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.I)
        if m:
            return unescape(re.sub(r"\s+", " ", m.group(1)).strip())[:600]
    return ""


class SearchContentSource:
    """通过搜索接口发现公开页面，再抓取正文作为 RAG 语料。"""

    def __init__(self, web_search: WebSearchTool | None = None) -> None:
        self.web_search = web_search or WebSearchTool()
        self.enabled = os.getenv("CONTENT_SOURCE_ENABLED", "false").lower() == "true"
        self.fetch_pages = os.getenv(
            "CONTENT_SOURCE_FETCH_PAGES", "false"
        ).lower() == "true"
        self.max_pages = max(1, int(os.getenv("CONTENT_SOURCE_MAX_PAGES", "3") or 3))
        self.allowed_domains = [
            d.strip()
            for d in os.getenv("CONTENT_SOURCE_DOMAINS", "").split(",")
            if d.strip()
        ]

    async def fetch_city(self, city: str, category: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        query = f"{city} {category} 攻略 推荐"
        try:
            results = await self.web_search.search(query, top_k=5)
        except Exception:
            return []

        candidates: list[tuple[dict[str, Any], str]] = []
        seen: set[str] = set()
        for item in results:
            url = item.get("url") or item.get("link") or ""
            if not url:
                if item.get("engine") != "builtin-fallback":
                    continue
                url = f"builtin://{item.get('id') or item.get('name')}"
            if url in seen or "y.js" in url or "ad_domain" in url:
                continue
            if self.allowed_domains and not any(d in url for d in self.allowed_domains):
                continue
            seen.add(url)
            candidates.append((item, url))

        fetched_map: dict[str, dict[str, Any]] = {}
        if self.fetch_pages and candidates:
            targets = candidates[: self.max_pages]
            tasks = [
                self._fetch_page(url, city, category) for _, url in targets
            ]
            fetched_list = await asyncio.gather(*tasks, return_exceptions=True)
            for (_, url), fetched in zip(targets, fetched_list):
                if isinstance(fetched, dict):
                    fetched_map[url] = fetched

        docs: list[dict[str, Any]] = []
        for item, url in candidates:
            title = item.get("name") or item.get("title") or f"{city}{category}攻略"
            snippet = item.get("content") or item.get("snippet") or ""
            source_label = (
                "内置语料（多平台搜索降级）"
                if item.get("engine") == "builtin-fallback"
                else f"搜索：{url}"
            )
            base_doc = {
                "id": url,
                "name": title,
                "city": city,
                "content": snippet,
                "source": source_label,
                "category": "attraction" if category == "景点" else "food",
                "url": url,
                "lat": CITY_CENTERS.get(city, (0, 0))[0],
                "lon": CITY_CENTERS.get(city, (0, 0))[1],
                "duration_hours": 0,
                "opening_hours": "全天",
                "fee": 80 if category == "景点" else 50,
                "tags": [category, city, "网页攻略"],
                "note": "来自多平台搜索，需人工复核",
                "title": title,
            }
            if url in fetched_map:
                base_doc = fetched_map[url]
            docs.append(base_doc)
        return docs

    async def _fetch_page(
        self, url: str, city: str, category: str
    ) -> dict[str, Any] | None:
        if not url.startswith("http"):
            return None
        cached = _PAGE_CACHE.get(url)
        if cached and time.time() - cached[0] < _PAGE_CACHE_TTL:
            return deepcopy(cached[1])

        try:
            async def _fetch() -> httpx.Response:
                last_error: Exception | None = None
                for attempt in range(3):
                    try:
                        async with httpx.AsyncClient(
                            timeout=8,
                            follow_redirects=True,
                            headers=_HTTP_HEADERS,
                        ) as client:
                            resp = await client.get(url)
                            resp.raise_for_status()
                            return resp
                    except Exception as exc:
                        last_error = exc
                        if attempt < 2:
                            await asyncio.sleep(0.5 * (attempt + 1))
                raise last_error or RuntimeError("fetch failed")

            resp = await asyncio.wait_for(_fetch(), timeout=15)
            html = _decode_response(resp)
            content = _extract_text(html)
            if len(content) < 80:
                content = _meta_description(html)
            if len(content) < 40:
                return None
            doc = {
                "id": url,
                "name": url,
                "city": city,
                "content": content,
                "source": f"公开网页：{url}",
                "category": "attraction" if category == "景点" else "food",
                "url": url,
                "lat": CITY_CENTERS.get(city, (0, 0))[0],
                "lon": CITY_CENTERS.get(city, (0, 0))[1],
                "duration_hours": 0,
                "opening_hours": "全天",
                "fee": 80 if category == "景点" else 50,
                "tags": [category, city, "网页攻略"],
                "note": "由公开内容源抓取，需人工复核",
                "title": "",
            }
            if len(_PAGE_CACHE) >= _PAGE_CACHE_MAX:
                _PAGE_CACHE.pop(next(iter(_PAGE_CACHE)), None)
            _PAGE_CACHE[url] = (time.time(), doc)
            return deepcopy(doc)
        except Exception:
            return None

