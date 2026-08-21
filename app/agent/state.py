"""LangGraph 状态定义。"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict


def _agent_results_reducer(
    left: list[dict[str, Any]] | None, right: Any
) -> list[dict[str, Any]]:
    if right is None:
        return []
    return (left or []) + right


class TravelState(TypedDict, total=False):
    user_input: str
    user_id: int | None
    trip_id: str
    intent: str
    params: dict[str, Any]
    docs: list[dict[str, Any]]
    task_plan: dict[str, Any]
    agent_results: Annotated[list[dict[str, Any]], _agent_results_reducer]
    existing_trip: dict[str, Any]
    existing_plan: dict[str, Any]
    itinerary: dict[str, Any]
    version: int
    validation: dict[str, Any]
    response: str
    history: Annotated[list[dict[str, Any]], add]
    tool_calls: Annotated[list[dict[str, Any]], add]
    errors: Annotated[list[str], add]

