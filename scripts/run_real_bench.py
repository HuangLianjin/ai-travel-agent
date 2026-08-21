"""真实行程批量跑测：调用线上 API 生成多城市行程，输出运行数据。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.security import hash_password  # noqa: E402

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
    "哈尔滨3天2人，预算3200，喜欢冰雪和历史",
    "沈阳2天1人，预算1600，喜欢美食和人文",
    "济南2天1人，预算1500，喜欢泉水和文化",
    "郑州2天1人，预算1400，喜欢历史和小吃",
    "合肥2天1人，预算1500，喜欢自然和美食",
    "南昌3天2人，预算2600，喜欢历史和美食",
    "昆明3天2人，预算3800，喜欢自然和慢节奏",
    "贵阳3天2人，预算3000，喜欢山水和美食",
    "南宁2天1人，预算1600，喜欢小吃和城市",
    "海口3天2人，预算3500，喜欢海边和美食",
    "兰州2天1人，预算1400，喜欢面和人文",
    "西宁3天2人，预算3200，喜欢自然和历史",
    "银川2天1人，预算1500，喜欢人文和自然",
    "乌鲁木齐3天2人，预算3800，喜欢美食和自然",
    "拉萨4天2人，预算6000，喜欢文化和自然",
    "珠海2天1人，预算1800，喜欢海边和夜景",
    "泉州3天2人，预算2800，喜欢美食和历史",
    "温州2天1人，预算1500，喜欢山水和美食",
    "洛阳3天2人，预算2600，喜欢历史和美食",
    "张家界4天2人，预算5000，喜欢自然和拍照",
]


def ensure_user(db_path: str, username: str, password: str, phone: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row:
            return int(row[0])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = con.execute(
            "INSERT INTO users (username, password_hash, role, status, created_at, phone, phone_verified) "
            "VALUES (?, ?, 'user', 'active', ?, ?, 1)",
            (username, hash_password(password), now, phone),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--output", default="data/bench_results.json")
    parser.add_argument("--db", default=str(ROOT / "data" / "travel.db"))
    args = parser.parse_args()

    suffix = str(int(time.time()))[-6:]
    username = f"bench_{suffix}"
    password = "BenchPass#2026"
    phone = f"139{suffix}0001"
    client = httpx.Client(timeout=300)

    ensure_user(args.db, username, password, phone)
    login = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    if login.status_code != 200:
        print("login failed", login.status_code, login.text)
        return
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
