"""
动作仓储接口
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.models.action import Action


class ActionRepository(ABC):
    """动作仓储接口"""

    @abstractmethod
    async def save(self, action: Action) -> Action:
        """保存动作"""
        pass

    @abstractmethod
    async def find_by_idempotency_key(self, idempotency_key: str) -> Optional[Action]:
        """按幂等键查询动作"""
        pass

    @abstractmethod
    async def find_recent_successful_message(
        self,
        seller_id: str,
        since_iso: str,
    ) -> Optional[Action]:
        """查询卖家冷却时间窗口内最近一次成功发送的消息动作"""
        pass

    @abstractmethod
    async def list_actions(
        self,
        *,
        limit: int = 100,
        task_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> list[Action]:
        """查询动作列表"""
        pass
