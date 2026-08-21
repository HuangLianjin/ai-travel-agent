"""真实行程批量跑测：调用线上 API 生成多城市行程，输出运行数据。"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api"

PROMPTS = [
    "北京3天2人，预算3000，喜欢历史和美食",
    "成都2天1人，预算1500，喜欢火锅和自然",
    "上海3天2人，预算5000，喜欢夜景和拍照",
    "西安2天1人，预算2000，喜欢历史和美食",
    "杭州3天2人，预算4000，喜欢自然和拍照",
    "广州2天1人，预算1800，喜欢美食和城市",
    "深圳2天1人，预算2000，喜欢海边和夜景",
    "南京3天2人，预算3500，喜欢历史和美食",
    "武汉2天1人，预算1500，喜欢小吃和人文",
    "长沙2天1人，预算1600，喜欢美食和夜生活",
    "重庆3天2人，预算4000，喜欢火锅和夜景",
    "厦门3天2人，预算3500，喜欢海边和拍照",
    "青岛2天1人，预算2000，喜欢海边和啤酒",
    "大理3天2人，预算4500，喜欢自然和慢节奏",
    "三亚4天2人，预算8000，喜欢海边和度假",
    "桂林3天2人，预算4000，喜欢自然和拍照",
    "苏州2天1人，预算1800，喜欢园林和美食",
    "丽江3天2人，预算4500，喜欢古镇和自然",
    "天津2天1人，预算1500，喜欢美食和城市",
    "福州3天2人，预算3000，喜欢美食和拍照",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--output", default="data/bench_results.json")
    args = parser.parse_args()

    suffix = str(int(time.time()))[-6:]
    username = f"bench_{suffix}"
    password = "bench123"
    client = httpx.Client(timeout=300)

    reg = client.post(f"{BASE}/auth/register", json={"username": username, "password": password})
    if reg.status_code not in (200, 409):
        print("register failed", reg.status_code, reg.text)
        return
    login = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    login.raise_for_status()
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    prompts = PROMPTS[: args.count]
    results = []
    for idx, prompt in enumerate(prompts, 1):
        t0 = time.perf_counter()
        payload = {"message": prompt, "session_id": f"bench-{idx}"}
        try:
            resp = client.post(f"{BASE}/chat", json=payload, headers=headers)
            elapsed = int((time.perf_counter() - t0) * 1000)
            if resp.status_code != 200:
                results.append({"index": idx, "prompt": prompt, "status": "failed", "error": resp.text[:200], "latency_ms": elapsed})
                print(f"[{idx}/{len(prompts)}] FAILED {resp.status_code} {prompt[:20]}")
                continue
            data = resp.json()
            itinerary = data.get("itinerary") or {}
            days = itinerary.get("days") or []
            budget = itinerary.get("budget") or {}
            results.append({
                "index": idx,
                "prompt": prompt,
                "status": "success" if data.get("run_id") else "failed",
                "run_id": data.get("run_id", ""),
                "trip_id": data.get("trip_id", ""),
                "days": len(days),
                "first_attrs": len((days[0].get("attractions") or []) if days else []),
                "first_dining": len((days[0].get("dining") or []) if days else []),
                "budget_total": budget.get("estimated_total"),
                "within_budget": budget.get("within_budget"),
                "latency_ms": elapsed,
            })
            print(f"[{idx}/{len(prompts)}] OK {prompt[:16]} days={len(days)} budget={budget.get('estimated_total')} {elapsed}ms")
        except Exception as exc:
            results.append({"index": idx, "prompt": prompt, "status": "failed", "error": str(exc)[:200], "latency_ms": int((time.perf_counter() - t0) * 1000)})
            print(f"[{idx}/{len(prompts)}] ERROR {exc}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "results": results,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
