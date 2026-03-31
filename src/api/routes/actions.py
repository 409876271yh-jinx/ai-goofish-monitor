"""
动作记录路由
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from src.infrastructure.persistence.sqlite_action_repository import SqliteActionRepository


router = APIRouter(prefix="/api/actions", tags=["actions"])


def _serialize_action(action) -> dict:
    payload = action.model_dump()
    action_payload = payload.get("payload") or {}
    item_snapshot = action_payload.get("item_snapshot") or {}
    analysis_summary = action_payload.get("analysis_summary") or {}
    order_candidate = action_payload.get("order_candidate") or {}
    executor_result = action_payload.get("executor_result") or {}
    payload["summary"] = {
        "task_name": action_payload.get("task_name") or "",
        "title": item_snapshot.get("title") or order_candidate.get("title") or "",
        "price": item_snapshot.get("price") or order_candidate.get("price") or "",
        "link": item_snapshot.get("link") or order_candidate.get("link") or "",
        "reason": analysis_summary.get("reason") or order_candidate.get("reason") or "",
        "risk_tags": analysis_summary.get("risk_tags") or order_candidate.get("risk_flags") or [],
        "template_id": action_payload.get("template_id"),
        "executor_status": executor_result.get("status"),
    }
    return payload


@router.get("", response_model=list[dict])
async def list_actions(
    limit: int = Query(default=100, ge=1, le=500),
    task_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
):
    repository = SqliteActionRepository()
    actions = await repository.list_actions(limit=limit, task_id=task_id, status=status)
    return [_serialize_action(action) for action in actions]
