from pathlib import Path

p = Path(r"D:\GitHub\ai-travel-agent\scripts\smoke.py")
s = p.read_text(encoding="utf-8")

old = """    check(
        "GET /api/trips",
        lambda: client.get(f"{BASE}/trips", headers=dh).raise_for_status(),
    )
"""
new = """    keep_days = check(
        "POST /api/chat keep days without day mention",
        lambda: client.post(
            f"{BASE}/chat",
            headers=dh,
            json={"message": "生成金额太少了", "trip_id": trip_id},
        ).raise_for_status(),
    )
    if keep_days:
        days_kept = len((keep_days.get("itinerary") or {}).get("days", []))
        results.append(
            (
                "Days preserved when only budget mentioned",
                days_kept == 6,
                f"days={days_kept}",
            )
        )

    check(
        "GET /api/trips",
        lambda: client.get(f"{BASE}/trips", headers=dh).raise_for_status(),
    )
"""

assert old in s
p.write_text(s.replace(old, new), encoding="utf-8")
print("patched smoke keep days")
