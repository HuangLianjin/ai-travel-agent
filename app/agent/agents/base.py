"""子 Agent 统一协议：Subtask / AgentResult / BaseTravelAgent。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.observability.metrics import metrics


@dataclass
class Subtask:
    task_id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    priority: int = 1
    parallel: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResult:
    agent: str
    status: str = "success"
    data: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseTravelAgent:
    """子 Agent 基类。"""

    name = "base"

    def __init__(
        self,
        searcher: Any = None,
        web_search: Any = None,
        map_mcp: Any = None,
        settings: Any = None,
        content_source: Any = None,
        llm: Any = None,
    ) -> None:
        self.searcher = searcher
        self.web_search = web_search
        self.map_mcp = map_mcp
        self.settings = settings
        self.content_source = content_source
        self.llm = llm

    async def run(self, subtask: Subtask, context: dict[str, Any]) -> AgentResult:
        t0 = time.perf_counter()
        try:
            data = await self._run(subtask, context)
            status = "success"
            error = ""
        except Exception as exc:
            data = {}
            status = "failed"
            error = str(exc)
            import sys
            import traceback

            print(f"[agent-error] {self.name}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        latency = int((time.perf_counter() - t0) * 1000)
        metrics.record_agent(self.name, status, latency)
        return AgentResult(
            agent=self.name,
            status=status,
            data=data,
            sources=self._sources(context),
            tool_calls=self._tool_calls(context),
            latency_ms=latency,
            error=error,
        )

    async def _run(
        self, subtask: Subtask, context: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _sources(self, context: dict[str, Any]) -> list[str]:
        docs = context.get("docs", [])
        return sorted({d.get("source", "") for d in docs if d.get("source")})

    def _tool_calls(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        return list(context.get("tool_calls", []) or [])

