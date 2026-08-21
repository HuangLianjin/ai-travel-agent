"""离线评测运行器：输出通过率、失败类型统计与 JSON 报告。"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.agent.agents.main_agent import MainAgent
from app.eval.cases import load_cases
from app.observability.metrics import metrics
from app.rag.search import HybridSearcher
from app.services.planner import (
    apply_adjustment,
    build_itinerary,
    detect_intent,
    extract_params,
    format_reply,
)


def _eval_one(case, searcher: HybridSearcher) -> dict[str, Any]:
    t0 = time.perf_counter()
    intent = detect_intent(case.input_text, has_trip=case.expected_intent == "adjust")
    params = extract_params(case.input_text)
    if intent == "adjust":
        params["city"] = case.expected_city
    docs = searcher.hybrid_search(case.expected_city, top_k=12)
    if intent == "adjust":
        base_plan = build_itinerary(params, docs, searcher)
        plan = apply_adjustment(base_plan, case.input_text, docs, params)
    else:
        plan = build_itinerary(params, docs, searcher)
    reply = format_reply(plan, intent)
    elapsed = int((time.perf_counter() - t0) * 1000)

    failures: list[str] = []
    if intent != case.expected_intent:
        failures.append("intent_mismatch")
    if params.get("city") != case.expected_city:
        failures.append("city_mismatch")
    if intent == "create":
        for key, value in case.expected_params.items():
            if params.get(key) != value:
                failures.append(f"param_{key}")
    missing = [kw for kw in case.expected_keywords if kw not in reply]
    if missing:
        failures.append("keyword_missing")
    present_absent = []
    for kw in case.expected_absent:
        for day in plan.get("days", []) or []:
            names = [
                str(a.get("name", ""))
                for a in (day.get("attractions", []) or [])
                + (day.get("dining", []) or [])
            ]
            if any(kw in n for n in names):
                present_absent.append(kw)
                break
    if present_absent:
        failures.append("absent_found")
    if not plan.get("valid"):
        failures.append("validation_failed")

    passed = not failures
    failure_type = failures[0] if failures else ""

    budget = plan.get("budget") or {}
    budget_ok = budget.get("within_budget") is not False and int(
        budget.get("estimated_total", 0)
    ) <= int(params.get("budget") or 99999999)
    days_expected = case.expected_params.get("days")
    days_ok = days_expected is None or len(plan.get("days", []) or []) == days_expected
    route_times = [
        sum(leg.get("minutes", 0) for leg in day.get("route", []) or [])
        for day in plan.get("days", []) or []
    ]
    route_ok = bool(route_times) and (sum(route_times) / len(route_times)) <= 180
    source_ok = bool(plan.get("sources"))

    quality_failures = []
    if not budget_ok:
        quality_failures.append("budget")
    if not days_ok:
        quality_failures.append("days")
    if not route_ok:
        quality_failures.append("route")
    if not source_ok:
        quality_failures.append("source")
    quality_score = round(
        (4 - len(quality_failures)) / 4, 2
    )

    metrics.record_eval(passed, failure_type)
    return {
        "case_id": case.case_id,
        "title": case.title,
        "passed": passed,
        "failure_types": failures,
        "quality_score": quality_score,
        "quality_failures": quality_failures,
        "intent": intent,
        "city": params.get("city"),
        "latency_ms": elapsed,
    }


async def _eval_main_agent(case, main_agent: MainAgent) -> dict[str, Any]:
    state = await main_agent.plan(
        {
            "user_input": case.input_text,
            "existing_trip": {"params": {}, "itinerary": {}}
            if case.expected_intent == "adjust"
            else None,
        }
    )
    intent = state.get("intent", "")
    subtask_types = [
        st.get("type") for st in (state.get("task_plan", {}).get("subtasks") or [])
    ]
    failures: list[str] = []
    if intent != case.expected_intent:
        failures.append("main_intent_mismatch")
    if case.expected_intent == "create":
        if set(subtask_types) != {"attraction", "food", "transport"}:
            failures.append("taskplan_create")
    elif case.expected_intent == "adjust":
        changed_fields = state.get("task_plan", {}).get("changed_fields", [])
        if not subtask_types and set(changed_fields) != {"date"}:
            failures.append("taskplan_adjust")
    elif case.expected_intent in ("ask", "chat"):
        if subtask_types:
            failures.append("taskplan_chat")
    return {
        "case_id": f"main_{case.case_id}",
        "title": case.title,
        "passed": not failures,
        "failure_types": failures,
        "intent": intent,
        "subtasks": subtask_types,
    }


async def run_demo_eval(cases=None) -> dict[str, Any]:
    cases = cases or load_cases()
    searcher = HybridSearcher()
    results = [_eval_one(case, searcher) for case in cases]
    main_agent = MainAgent()
    main_results = [await _eval_main_agent(case, main_agent) for case in cases]
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failure_types: dict[str, int] = {}
    quality_failures: dict[str, int] = {}
    for r in results:
        for ft in r["failure_types"]:
            failure_types[ft] = failure_types.get(ft, 0) + 1
        for qf in r.get("quality_failures", []):
            quality_failures[qf] = quality_failures.get(qf, 0) + 1
    quality_scores = [r.get("quality_score", 0) for r in results]
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "avg_quality_score": round(sum(quality_scores) / total, 4) if total else 0.0,
        "quality_failures": quality_failures,
        "failure_types": failure_types,
        "avg_latency_ms": round(
            sum(r["latency_ms"] for r in results) / total, 2
        )
        if total
        else 0.0,
        "cases": results,
        "main_agent": {
            "total": len(main_results),
            "passed": sum(1 for r in main_results if r["passed"]),
            "pass_rate": round(
                sum(1 for r in main_results if r["passed"]) / len(main_results), 4
            )
            if main_results
            else 0.0,
            "cases": main_results,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="星旅 Agent 离线评测")
    parser.add_argument("--output", default="data/eval_report.json")
    args = parser.parse_args()
    report = asyncio.run(run_demo_eval())
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

