"""
动作领域模型
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ActionType = Literal["send_message", "create_order_candidate", "skip"]
ActionStatus = Literal["pending", "running", "success", "failed", "cancelled"]


def _now_iso() -> str:
    return datetime.now().isoformat()


class Action(BaseModel):
    """动作实体"""

    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    task_id: Optional[int] = None
    item_id: str
    seller_id: Optional[str] = None
    action_type: ActionType
    status: ActionStatus = "pending"
    payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    retry_count: int = 0
    last_error: str = ""
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    def with_status(
        self,
        status: ActionStatus,
        *,
        last_error: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        retry_count: Optional[int] = None,
    ) -> "Action":
        update: Dict[str, Any] = {
            "status": status,
            "updated_at": _now_iso(),
        }
        if last_error is not None:
            update["last_error"] = last_error
        if payload is not None:
            update["payload"] = payload
        if retry_count is not None:
            update["retry_count"] = retry_count
        return self.model_copy(update=update)
