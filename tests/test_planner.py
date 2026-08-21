import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.agents.specialists import SynthesisAgent, _is_listing_title
from app.services.planner import _to_int, _transport_cost, _transport_units


def test_taxi_two_people_one_car():
    assert _transport_units("打车", 2) == 1


def test_taxi_five_people_two_cars():
    assert _transport_units("打车", 5) == 2


def test_transit_per_person():
    assert _transport_units("公共交通", 2) == 2


def test_transport_cost_uses_car_count():
    items = [{"cost_yuan": 30, "mode": "打车"}]
    assert _transport_cost(items, 2) == 30
    assert _transport_cost(items, 5) == 60


def test_transport_cost_transit_per_person():
    items = [{"cost_yuan": 3, "mode": "公共交通"}]
    assert _transport_cost(items, 2) == 6


def test_to_int_extracts_number():
    assert _to_int("人均30元") == 30
    assert _to_int("¥88") == 88
    assert _to_int(None) == 0


def test_listing_title_filter():
    assert _is_listing_title("福州9家本地人私藏餐厅美食清单")
    assert not _is_listing_title("同利肉燕老铺(三坊七巷店)")


def test_rule_clean_docs_dedup_and_filter():
    docs = [
        {"name": "老店A", "category": "food"},
        {"name": "老店A", "category": "food"},
        {"name": "福州美食清单", "category": "food"},
    ]
    cleaned = SynthesisAgent._rule_clean_docs(docs, {"days": 2})
    names = [d["name"] for d in cleaned]
    assert names.count("老店A") == 1
    assert "福州美食清单" not in names


def test_normalize_llm_timeline():
    tl = [
        {"time": "12:00-13:00", "type": "午餐", "title": "餐厅A", "duration_minutes": 60},
        {"time": "18:30", "type": "晚餐", "title": "餐厅B"},
    ]
    out = SynthesisAgent._normalize_llm_timeline(tl)
    assert len(out) == 2
    assert out[0]["type"] == "food"
    assert out[1]["time_minutes"] == 18 * 60 + 30
