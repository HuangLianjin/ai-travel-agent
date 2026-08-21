"""进程内指标采集：成功率、延迟、失败类型、工具调用、审核与评测。"""

from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Any


class AgentMetrics:
    def __init__(self, max_latency_samples: int = 500) -> None:
        self._lock = threading.Lock()
        self._max = max_latency_samples
        self.started_at = time.time()
        self.request_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.latency_ms: deque[float] = deque(maxlen=max_latency_samples)
        self.stage_counts: Counter[str] = Counter()
        self.tool_counts: Counter[str] = Counter()
        self.agent_counts: Counter[str] = Counter()
        self.agent_failures: Counter[str] = Counter()
        self.failure_types: Counter[str] = Counter()
        self.reviews_created = 0
        self.reviews_approved = 0
        self.reviews_rejected = 0
        self.eval_total = 0
        self.eval_passed = 0
        self.eval_failures: Counter[str] = Counter()
        self.llm_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def record_request(self) -> None:
        with self._lock:
            self.request_count += 1

    def record_success(self, latency_ms: float, stage: str = "") -> None:
        with self._lock:
            self.success_count += 1
            self.latency_ms.append(latency_ms)
            if stage:
                self.stage_counts[stage] += 1

    def record_failure(
        self, latency_ms: float, failure_type: str = "agent_error", stage: str = ""
    ) -> None:
        with self._lock:
            self.failure_count += 1
            self.latency_ms.append(latency_ms)
            self.failure_types[failure_type] += 1
            if stage:
                self.stage_counts[stage] += 1

    def record_stage(self, stage: str) -> None:
        with self._lock:
            self.stage_counts[stage] += 1

    def record_tool(self, name: str) -> None:
        with self._lock:
            self.tool_counts[name] += 1

    def record_agent(self, name: str, status: str, latency_ms: int = 0) -> None:
        with self._lock:
            self.agent_counts[name] += 1
            self.latency_ms.append(latency_ms)
            if status != "success":
                self.agent_failures[name] += 1

    def record_review(self, action: str) -> None:
        with self._lock:
            if action == "created":
                self.reviews_created += 1
            elif action == "approved":
                self.reviews_approved += 1
            elif action == "rejected":
                self.reviews_rejected += 1

    def record_llm_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        with self._lock:
            self.llm_calls += 1
            self.prompt_tokens += int(prompt_tokens)
            self.completion_tokens += int(completion_tokens)
            self.total_tokens += int(prompt_tokens) + int(completion_tokens)

    def record_eval(self, passed: bool, failure_type: str = "") -> None:
        with self._lock:
            self.eval_total += 1
            if passed:
                self.eval_passed += 1
            elif failure_type:
                self.eval_failures[failure_type] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self.latency_ms)
            avg = sum(samples) / len(samples) if samples else 0.0
            ordered = sorted(samples)
            p95 = (
                ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
                if ordered
                else 0.0
            )
            return {
                "uptime_seconds": round(time.time() - self.started_at, 3),
                "request_count": self.request_count,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "success_rate": round(
                    self.success_count / self.request_count, 4
                )
                if self.request_count
                else 0.0,
                "avg_latency_ms": round(avg, 3),
                "p95_latency_ms": round(p95, 3),
                "stage_counts": dict(self.stage_counts),
                "tool_counts": dict(self.tool_counts),
                "agent_counts": dict(self.agent_counts),
                "agent_failures": dict(self.agent_failures),
                "failure_types": dict(self.failure_types),
                "reviews_created": self.reviews_created,
                "reviews_approved": self.reviews_approved,
                "reviews_rejected": self.reviews_rejected,
                "eval_total": self.eval_total,
                "eval_passed": self.eval_passed,
                "llm_calls": self.llm_calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "eval_pass_rate": round(
                    self.eval_passed / self.eval_total, 4
                )
                if self.eval_total
                else 0.0,
                "eval_failures": dict(self.eval_failures),
            }

    def reset(self) -> None:
        with self._lock:
            self.__init__(self._max)


metrics = AgentMetrics()

