"""LLM 客户端：demo 模式离线可用，openai 模式走 OpenAI 兼容接口。"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.observability.metrics import metrics

_LLM_INSTANCES: dict[str, "TravelLLM"] = {}


def get_llm(settings: Settings | None = None) -> "TravelLLM":
    settings = settings or get_settings()
    key = (
        f"{settings.llm_mode}:{settings.openai_base_url}:{settings.model_name}"
    )
    if key not in _LLM_INSTANCES:
        _LLM_INSTANCES[key] = TravelLLM(settings)
    return _LLM_INSTANCES[key]


class TravelLLM:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, system: str, user: str) -> str:
        if self.settings.llm_mode == "openai" and self.settings.openai_api_key:
            return await self._openai_complete(system, user)
        return self._demo_complete(system, user)

    async def _openai_complete(self, system: str, user: str) -> str:
        url = self.settings.openai_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage") or {}
            metrics.record_llm_usage(
                int(usage.get("prompt_tokens", 0) or 0),
                int(usage.get("completion_tokens", 0) or 0),
            )
            return data["choices"][0]["message"]["content"]

    def _demo_complete(self, system: str, user: str) -> str:
        if "谢谢" in user or "你好" in user:
            return "好的，随时告诉我你想去哪里玩。"
        return "我会用内置规则引擎完成参数提取、RAG 检索与行程校验，确保可离线演示。"

