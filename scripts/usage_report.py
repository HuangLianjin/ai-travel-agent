"""根据 agent_runs 生成可写入简历的运行指标报告（PostgreSQL）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import Database  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Agent 运行指标报告")
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL", ""), help="PostgreSQL 连接串")
    parser.add_argument("--user-id", type=int, default=None, help="只统计指定用户的运行记录")
    parser.add_argument("--output", default=str(ROOT / "data" / "usage_report.json"))
    parser.add_argument(
        "--input-price-per-1m",
        type=float,
        default=float(os.getenv("LLM_INPUT_PRICE_PER_1M", "2.0")),
        help="DeepSeek 输入价格，单位：元/百万 token",
    )
    parser.add_argument(
        "--output-price-per-1m",
        type=float,
        default=float(os.getenv("LLM_OUTPUT_PRICE_PER_1M", "8.0")),
        help="DeepSeek 输出价格，单位：元/百万 token",
    )
    args = parser.parse_args()

    dsn = args.dsn or get_settings().db_dsn
    db = Database(dsn)
    where = " WHERE user_id = %s" if args.user_id is not None else ""
    params = (args.user_id,) if args.user_id is not None else ()
    rows = db.query_all(
        "SELECT intent, status, prompt_tokens, completion_tokens, latency_ms, created_at "
        "FROM agent_runs" + where + " ORDER BY created_at ASC",
        params,
    )
    db.close()

    total = len(rows)
    success = sum(1 for r in rows if r["status"] == "success")
    failed = sum(1 for r in rows if r["status"] == "failed")
    prompt_tokens = sum(int(r["prompt_tokens"] or 0) for r in rows)
    completion_tokens = sum(int(r["completion_tokens"] or 0) for r in rows)
    total_tokens = prompt_tokens + completion_tokens
    latencies = [int(r["latency_ms"] or 0) for r in rows]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    sorted_latency = sorted(latencies)
    p95 = (
        sorted_latency[min(len(sorted_latency) - 1, int(len(sorted_latency) * 0.95))]
        if sorted_latency
        else 0
    )
    cost = round(
        prompt_tokens / 1_000_000 * args.input_price_per_1m
        + completion_tokens / 1_000_000 * args.output_price_per_1m,
        4,
    )

    by_intent: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in rows:
        by_intent[r["intent"]] = by_intent.get(r["intent"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_runs": total,
        "success_runs": success,
        "failed_runs": failed,
        "success_rate": round(success / total, 4) if total else 0.0,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_yuan": cost,
        "input_price_per_1m": args.input_price_per_1m,
        "output_price_per_1m": args.output_price_per_1m,
        "by_intent": by_intent,
        "by_status": by_status,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
