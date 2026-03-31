"""
基于 SQLite 的动作仓储实现。
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from src.domain.models.action import Action
from src.domain.repositories.action_repository import ActionRepository
from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


def _row_to_action(row) -> Action:
    payload = dict(row)
    payload["payload"] = json.loads(payload.pop("payload_json") or "{}")
    return Action(**payload)


class SqliteActionRepository(ActionRepository):
    """基于 SQLite 的动作仓储"""

    def __init__(
        self,
        db_path: str | None = None,
        legacy_config_file: str | None = "config.json",
    ) -> None:
        self.db_path = db_path
        self.legacy_config_file = legacy_config_file

    async def save(self, action: Action) -> Action:
        return await asyncio.to_thread(self._save_sync, action)

    async def find_by_idempotency_key(self, idempotency_key: str) -> Optional[Action]:
        return await asyncio.to_thread(
            self._find_by_idempotency_key_sync,
            idempotency_key,
        )

    async def find_recent_successful_message(
        self,
        seller_id: str,
        since_iso: str,
    ) -> Optional[Action]:
        return await asyncio.to_thread(
            self._find_recent_successful_message_sync,
            seller_id,
            since_iso,
        )

    async def list_actions(
        self,
        *,
        limit: int = 100,
        task_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> list[Action]:
        return await asyncio.to_thread(
            self._list_actions_sync,
            limit,
            task_id,
            status,
        )

    def _bootstrap(self) -> None:
        bootstrap_sqlite_storage(
            self.db_path,
            legacy_config_file=self.legacy_config_file,
        )

    def _save_sync(self, action: Action) -> Action:
        self._bootstrap()
        with sqlite_connection(self.db_path) as conn:
            action_id = action.id
            if action_id is None:
                conn.execute(
                    """
                    INSERT INTO actions (
                        task_id, item_id, seller_id, action_type, status,
                        payload_json, idempotency_key, retry_count, last_error,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.task_id,
                        action.item_id,
                        action.seller_id,
                        action.action_type,
                        action.status,
                        json.dumps(action.payload or {}, ensure_ascii=False),
                        action.idempotency_key,
                        int(action.retry_count or 0),
                        action.last_error or "",
                        action.created_at,
                        action.updated_at,
                    ),
                )
                action_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            else:
                conn.execute(
                    """
                    UPDATE actions
                    SET task_id = ?,
                        item_id = ?,
                        seller_id = ?,
                        action_type = ?,
                        status = ?,
                        payload_json = ?,
                        idempotency_key = ?,
                        retry_count = ?,
                        last_error = ?,
                        created_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        action.task_id,
                        action.item_id,
                        action.seller_id,
                        action.action_type,
                        action.status,
                        json.dumps(action.payload or {}, ensure_ascii=False),
                        action.idempotency_key,
                        int(action.retry_count or 0),
                        action.last_error or "",
                        action.created_at,
                        action.updated_at,
                        action_id,
                    ),
                )
            conn.commit()
        return action.model_copy(update={"id": action_id})

    def _find_by_idempotency_key_sync(self, idempotency_key: str) -> Optional[Action]:
        self._bootstrap()
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM actions
                WHERE idempotency_key = ?
                LIMIT 1
                """,
                (idempotency_key,),
            ).fetchone()
        return _row_to_action(row) if row else None

    def _find_recent_successful_message_sync(
        self,
        seller_id: str,
        since_iso: str,
    ) -> Optional[Action]:
        self._bootstrap()
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM actions
                WHERE seller_id = ?
                  AND action_type = 'send_message'
                  AND status = 'success'
                  AND created_at >= ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (seller_id, since_iso),
            ).fetchone()
        return _row_to_action(row) if row else None

    def _list_actions_sync(
        self,
        limit: int,
        task_id: Optional[int],
        status: Optional[str],
    ) -> list[Action]:
        self._bootstrap()
        conditions: list[str] = []
        params: list[object] = []
        if task_id is not None:
            conditions.append("task_id = ?")
            params.append(task_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM actions
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                tuple(params + [max(1, min(int(limit), 500))]),
            ).fetchall()
        return [_row_to_action(row) for row in rows]
