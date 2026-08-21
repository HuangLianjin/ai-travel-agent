from pathlib import Path


def replace_in(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    assert old in s, f"block not found in {path}: {old[:100]}"
    p.write_text(s.replace(old, new), encoding="utf-8")


planner = r"D:\GitHub\ai-travel-agent\app\services\planner.py"
s = Path(planner).read_text(encoding="utf-8")

old_parse = """def _parse_count(text: str, unit: str, default: int) -> int:
    m = re.search(rf"([0-9一二两三四五六七八九十]+)\\s*个?\\s*{unit}", text)
    if not m:
        return default
"""
new_parse = """def _parse_count(text: str, unit: str, default: int | None) -> int | None:
    m = re.search(rf"([0-9一二两三四五六七八九十]+)\\s*个?\\s*{unit}", text)
    if not m:
        return default
"""
assert old_parse in s
s = s.replace(old_parse, new_parse)

old_extract = """def extract_params(text: str) -> dict[str, Any]:
    days = _parse_count(text, "天", 2)
    travelers = _parse_count(text, "人", 1)

    budget = 3000
    for pattern in (
        r"(?:预算|花费|不能超过|不超过|控制在|上限)\\s*(\\d{3,6})\\s*(?:元|块)?",
        r"(\\d{3,6})\\s*元",
        r"(\\d{3,6})\\s*以内",
    ):
        m = re.search(pattern, text)
        if m:
            budget = int(m.group(1))
            break
"""
new_extract = """def extract_params(text: str) -> dict[str, Any]:
    explicit: list[str] = []

    days = _parse_count(text, "天", None)
    if days is not None:
        explicit.append("days")
    days = days or 2

    travelers = _parse_count(text, "人", None)
    if travelers is not None:
        explicit.append("travelers")
    travelers = travelers or 1

    budget: int | None = None
    for pattern in (
        r"(?:预算|花费|不能超过|不超过|控制在|上限)\\s*(\\d{3,6})\\s*(?:元|块)?",
        r"(\\d{3,6})\\s*元",
        r"(\\d{3,6})\\s*以内",
    ):
        m = re.search(pattern, text)
        if m:
            budget = int(m.group(1))
            explicit.append("budget")
            break
"""
assert old_extract in s
s = s.replace(old_extract, new_extract)

old_return = """    return {
        "city": detect_city(text),
        "days": days,
        "travelers": travelers,
        "budget": budget,
        "transport": transport,
        "interests": list(dict.fromkeys(interests)),
        "source_text": text[:200],
    }
"""
new_return = """    return {
        "city": detect_city(text),
        "days": days,
        "travelers": travelers,
        "budget": budget or 3000,
        "transport": transport,
        "interests": list(dict.fromkeys(interests)),
        "source_text": text[:200],
        "_explicit_fields": explicit,
    }
"""
assert old_return in s
s = s.replace(old_return, new_return)
Path(planner).write_text(s, encoding="utf-8")

main = r"D:\GitHub\ai-travel-agent\app\agent\agents\main_agent.py"
s = Path(main).read_text(encoding="utf-8")
old_merge = """        params = extract_params(text)
        if trip:
            params = {**(trip.get("params") or {}), **params}
"""
new_merge = """        params = extract_params(text)
        if trip:
            merged = dict(trip.get("params") or {})
            explicit = set(params.pop("_explicit_fields", []))
            for key in explicit:
                merged[key] = params[key]
            merged["source_text"] = params.get("source_text", "")
            params = merged
"""
assert old_merge in s
s = s.replace(old_merge, new_merge)
Path(main).write_text(s, encoding="utf-8")

print("patched param merge")
