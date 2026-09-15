import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.eval.runner import _low_score_records


def test_low_score_records_include_failures_and_threshold_samples():
    report = {
        "cases": [
            {"case_id": "ok", "passed": True, "quality_score": 1.0},
            {"case_id": "quality", "passed": True, "quality_score": 0.75},
            {"case_id": "failed", "passed": False, "quality_score": 1.0},
        ],
        "main_agent": {
            "cases": [
                {"case_id": "main_ok", "passed": True},
                {"case_id": "main_failed", "passed": False},
            ]
        },
    }

    records = _low_score_records(report)

    assert [item["case_id"] for item in records] == [
        "quality",
        "failed",
        "main_failed",
    ]
