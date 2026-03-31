"""
动作执行服务
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from src.domain.models.action import Action, ActionType
from src.domain.repositories.action_repository import ActionRepository
from src.infrastructure.executors.browser_executor import BrowserExecutor
from src.services.message_template_service import MessageTemplateService
from src.services.notification_service import (
    NotificationService,
    build_notification_service,
)
from src.services.price_history_service import parse_price_value


DEFAULT_MIN_AI_SCORE = 0
DEFAULT_ORDER_CANDIDATE_SCORE = 75
DEFAULT_SELLER_COOLDOWN_SECONDS = 6 * 60 * 60
DEFAULT_PRIMARY_ACTION = "auto"
DEFAULT_RISK_WORDS = (
    "私聊微信",
    "加微信",
    "vx",
    "v信",
    "先付定金",
    "付定金",
    "脱离平台",
    "线下交易",
    "QQ",
)


@dataclass(frozen=True)
class ActionDecision:
    should_act: bool
    action_type: ActionType
    template_id: Optional[str]
    reason: str
    risk_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_act": self.should_act,
            "action_type": self.action_type,
            "template_id": self.template_id,
            "reason": self.reason,
            "risk_flags": list(self.risk_flags),
        }


class ActionService:
    """负责动作决策、规则校验、执行与通知。"""

    def __init__(
        self,
        repository: ActionRepository,
        *,
        message_template_service: Optional[MessageTemplateService] = None,
        notification_service: Optional[NotificationService] = None,
        browser_executor_factory: Optional[Callable[[], BrowserExecutor]] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._repository = repository
        self._message_template_service = (
            message_template_service or MessageTemplateService()
        )
        self._notification_service = notification_service or build_notification_service()
        self._browser_executor_factory = browser_executor_factory or BrowserExecutor
        self._now_provider = now_provider or datetime.now

    async def handle_recommended_item(
        self,
        *,
        task_id: Optional[int],
        task_name: str,
        record: dict,
        analysis_result: dict,
        login_state_path: Optional[str],
        seller_id: Optional[str],
        task_max_price: Optional[str] = None,
        action_settings: Optional[dict] = None,
    ) -> Action:
        decision = self.build_action_decision(
            record=record,
            analysis_result=analysis_result,
            action_settings=action_settings,
        )
        rule_violation = await self._apply_rules(
            record=record,
            decision=decision,
            seller_id=seller_id,
            task_max_price=task_max_price,
            action_settings=action_settings,
        )
        if rule_violation is not None:
            decision = ActionDecision(
                should_act=False,
                action_type="skip",
                template_id=None,
                reason=rule_violation,
                risk_flags=tuple(self._merge_risk_flags(decision.risk_flags, (rule_violation,))),
            )

        action = await self._create_action(
            task_id=task_id,
            seller_id=seller_id,
            record=record,
            decision=decision,
        )

        if action.action_type == "skip":
            action = await self._repository.save(
                action.with_status(
                    "cancelled",
                    last_error=decision.reason,
                    payload=self._merge_payload(
                        action.payload,
                        {"final_reason": decision.reason},
                    ),
                )
            )
            self._log_event("skip", action, reason=decision.reason)
            return action

        if action.action_type == "create_order_candidate":
            return await self._handle_order_candidate(action, record, decision)

        return await self._handle_send_message(
            action,
            record=record,
            decision=decision,
            login_state_path=login_state_path,
        )

    def build_action_decision(
        self,
        *,
        record: dict,
        analysis_result: dict,
        action_settings: Optional[dict] = None,
    ) -> ActionDecision:
        if not analysis_result.get("is_recommended"):
            return ActionDecision(
                should_act=False,
                action_type="skip",
                template_id=None,
                reason="AI/规则未推荐，跳过动作执行。",
                risk_flags=(),
            )

        risk_flags = tuple(
            str(flag).strip()
            for flag in analysis_result.get("risk_tags") or []
            if str(flag).strip()
        )
        score = self._resolve_ai_score(record, analysis_result)
        order_candidate_score = self._read_int_setting(
            action_settings,
            "order_candidate_score_threshold",
            DEFAULT_ORDER_CANDIDATE_SCORE,
        )
        item_info = record.get("商品信息", {}) or {}
        template_id = self._message_template_service.resolve_template_id(
            configured_template_id=self._read_str_setting(
                action_settings,
                "message_template_id",
                "auto",
            ),
            item_info=item_info,
            analysis_result=analysis_result,
        )
        primary_action = self._read_primary_action(action_settings)

        if primary_action == "send_message":
            return ActionDecision(
                should_act=True,
                action_type="send_message",
                template_id=template_id,
                reason=str(analysis_result.get("reason") or "命中推荐，准备发送首句咨询。"),
                risk_flags=risk_flags,
            )

        if primary_action == "create_order_candidate":
            return ActionDecision(
                should_act=True,
                action_type="create_order_candidate",
                template_id=None,
                reason=str(analysis_result.get("reason") or "命中推荐，准备生成候选下单。"),
                risk_flags=risk_flags,
            )

        if score is not None and score >= order_candidate_score and not risk_flags:
            return ActionDecision(
                should_act=True,
                action_type="create_order_candidate",
                template_id=None,
                reason=str(analysis_result.get("reason") or "价格和风险表现满足候选下单条件。"),
                risk_flags=risk_flags,
            )

        return ActionDecision(
            should_act=True,
            action_type="send_message",
            template_id=template_id,
            reason=str(analysis_result.get("reason") or "命中推荐，准备发送首句咨询。"),
            risk_flags=risk_flags,
        )

    async def _apply_rules(
        self,
        *,
        record: dict,
        decision: ActionDecision,
        seller_id: Optional[str],
        task_max_price: Optional[str],
        action_settings: Optional[dict],
    ) -> Optional[str]:
        item_info = record.get("商品信息", {}) or {}
        item_id = str(item_info.get("商品ID") or "").strip()
        action_type = decision.action_type
        idempotency_key = self._build_idempotency_key(item_id, action_type)
        existing = await self._repository.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return f"同一商品的动作已执行过，触发幂等保护: {idempotency_key}"

        max_price_value = parse_price_value(task_max_price)
        item_price_value = parse_price_value(item_info.get("当前售价"))
        if (
            max_price_value is not None
            and item_price_value is not None
            and item_price_value > max_price_value
        ):
            return f"商品价格 {item_price_value} 超出任务上限 {max_price_value}，跳过动作。"

        score = self._resolve_ai_score(record, record.get("ai_analysis", {}) or {})
        min_ai_score = self._read_int_setting(
            action_settings,
            "min_ai_score",
            DEFAULT_MIN_AI_SCORE,
        )
        if score is not None and score < min_ai_score:
            return f"AI 评分 {score} 低于阈值 {min_ai_score}，跳过动作。"

        risk_words = self._read_list_setting(
            action_settings,
            "risk_words",
            DEFAULT_RISK_WORDS,
        )
        matched_risk_words = self._match_risk_words(record, risk_words)
        if matched_risk_words:
            return "命中风险词，跳过动作: " + ", ".join(matched_risk_words)

        if action_type == "send_message" and seller_id:
            cooldown_seconds = self._read_int_setting(
                action_settings,
                "seller_cooldown_seconds",
                DEFAULT_SELLER_COOLDOWN_SECONDS,
            )
            since_iso = (self._now_provider() - timedelta(seconds=cooldown_seconds)).isoformat()
            recent_action = await self._repository.find_recent_successful_message(
                seller_id,
                since_iso,
            )
            if recent_action is not None:
                return (
                    f"卖家 {seller_id} 仍处于冷却期内，"
                    f"上次成功发送时间: {recent_action.created_at}"
                )

        return None

    async def _create_action(
        self,
        *,
        task_id: Optional[int],
        seller_id: Optional[str],
        record: dict,
        decision: ActionDecision,
    ) -> Action:
        item_info = record.get("商品信息", {}) or {}
        item_id = str(item_info.get("商品ID") or "").strip() or (
            str(item_info.get("商品链接") or "").strip()
        )
        payload = self._build_action_payload(record, decision)
        if decision.action_type == "skip":
            idempotency_key = (
                f"{item_id}:skip:{self._now_provider().isoformat(timespec='microseconds')}"
            )
        else:
            idempotency_key = self._build_idempotency_key(item_id, decision.action_type)
        action = Action(
            task_id=task_id,
            item_id=item_id,
            seller_id=seller_id,
            action_type=decision.action_type,
            status="pending",
            payload=payload,
            idempotency_key=idempotency_key,
        )
        saved_action = await self._repository.save(action)
        self._log_event("created", saved_action)
        return saved_action

    async def _handle_order_candidate(
        self,
        action: Action,
        record: dict,
        decision: ActionDecision,
    ) -> Action:
        item_info = record.get("商品信息", {}) or {}
        candidate_payload = self._merge_payload(
            action.payload,
            {
                "order_candidate": {
                    "item_id": action.item_id,
                    "title": item_info.get("商品标题", ""),
                    "price": item_info.get("当前售价", ""),
                    "reason": decision.reason,
                    "risk_flags": list(decision.risk_flags),
                    "link": item_info.get("商品链接", ""),
                }
            },
        )
        running_action = await self._repository.save(action.with_status("running"))
        notification_reason = (
            "[候选下单] 已生成待人工确认的候选单。\n"
            f"任务: {record.get('任务名称', '')}\n"
            f"商品ID: {action.item_id}\n"
            f"标题: {item_info.get('商品标题', '')}\n"
            f"价格: {item_info.get('当前售价', '')}\n"
            f"命中原因: {decision.reason}\n"
            f"风险标记: {', '.join(decision.risk_flags) if decision.risk_flags else '无'}\n"
            f"链接: {item_info.get('商品链接', '')}\n"
            "说明: 仅生成候选记录，不会自动付款。"
        )
        results = await self._notification_service.send_notification(item_info, notification_reason)
        updated_action = await self._repository.save(
            running_action.with_status(
                "success",
                payload=self._merge_payload(
                    candidate_payload,
                    {"notification_results": results},
                ),
            )
        )
        self._log_event("candidate_created", updated_action)
        return updated_action

    async def _handle_send_message(
        self,
        action: Action,
        *,
        record: dict,
        decision: ActionDecision,
        login_state_path: Optional[str],
    ) -> Action:
        item_info = record.get("商品信息", {}) or {}
        template_id = decision.template_id or "ask_availability"
        message = self._message_template_service.render_template(
            template_id,
            {
                "title": str(item_info.get("商品标题") or ""),
            },
        )
        running_action = await self._repository.save(action.with_status("running"))
        executor = self._browser_executor_factory()
        result = await executor.send_message(
            str(item_info.get("商品链接") or ""),
            message,
            login_state_path,
        )
        payload = self._merge_payload(
            action.payload,
            {
                "template_id": template_id,
                "message": message,
                "executor_result": {
                    "success": result.success,
                    "status": result.status,
                    "error": result.error,
                    "detail": result.detail,
                    "metadata": result.metadata,
                },
            },
        )

        if result.success:
            notification_reason = (
                "[自动沟通] 已发送首条模板消息。\n"
                f"模板: {template_id}\n"
                f"商品ID: {action.item_id}\n"
                f"原因: {decision.reason}\n"
                f"链接: {item_info.get('商品链接', '')}"
            )
            notification_results = await self._notification_service.send_notification(
                item_info,
                notification_reason,
            )
            updated_action = await self._repository.save(
                running_action.with_status(
                    "success",
                    payload=self._merge_payload(
                        payload,
                        {"notification_results": notification_results},
                    ),
                )
            )
            self._log_event("message_sent", updated_action)
            return updated_action

        failure_reason = (
            "[自动沟通失败] 已安全终止页面动作，并降级为通知。\n"
            f"模板: {template_id}\n"
            f"商品ID: {action.item_id}\n"
            f"原因: {decision.reason}\n"
            f"错误: {result.error or result.status}\n"
            f"详情: {result.detail or '无'}\n"
            f"链接: {item_info.get('商品链接', '')}"
        )
        notification_results = await self._notification_service.send_notification(
            item_info,
            failure_reason,
        )
        updated_action = await self._repository.save(
            running_action.with_status(
                "failed",
                last_error=result.detail or result.error or result.status,
                retry_count=running_action.retry_count + 1,
                payload=self._merge_payload(
                    payload,
                    {"notification_results": notification_results},
                ),
            )
        )
        self._log_event("message_failed", updated_action, error=result.error or result.status)
        return updated_action

    def _build_action_payload(self, record: dict, decision: ActionDecision) -> dict[str, Any]:
        item_info = record.get("商品信息", {}) or {}
        seller_info = record.get("卖家信息", {}) or {}
        return {
            "task_name": record.get("任务名称", ""),
            "decision": decision.to_dict(),
            "item_snapshot": {
                "item_id": item_info.get("商品ID", ""),
                "title": item_info.get("商品标题", ""),
                "price": item_info.get("当前售价", ""),
                "link": item_info.get("商品链接", ""),
            },
            "seller_snapshot": {
                "seller_id": seller_info.get("卖家ID", ""),
                "seller_nickname": seller_info.get("卖家昵称", ""),
            },
            "analysis_summary": {
                "analysis_source": record.get("ai_analysis", {}).get("analysis_source"),
                "reason": record.get("ai_analysis", {}).get("reason"),
                "risk_tags": record.get("ai_analysis", {}).get("risk_tags") or [],
                "value_score": self._resolve_ai_score(
                    record,
                    record.get("ai_analysis", {}) or {},
                ),
            },
        }

    def _build_idempotency_key(self, item_id: str, action_type: ActionType) -> str:
        safe_item_id = item_id or "unknown"
        return f"{safe_item_id}:{action_type}"

    def _resolve_ai_score(self, record: dict, analysis_result: dict) -> Optional[int]:
        candidates = [
            analysis_result.get("value_score"),
            (record.get("price_insight", {}) or {}).get("deal_score"),
        ]
        for candidate in candidates:
            try:
                if candidate is None or candidate == "":
                    continue
                return int(candidate)
            except (TypeError, ValueError):
                continue
        return None

    def _read_int_setting(
        self,
        action_settings: Optional[dict],
        key: str,
        default: int,
    ) -> int:
        if not isinstance(action_settings, dict):
            return default
        try:
            return int(action_settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def _read_str_setting(
        self,
        action_settings: Optional[dict],
        key: str,
        default: str,
    ) -> str:
        if not isinstance(action_settings, dict):
            return default
        value = action_settings.get(key, default)
        text = str(value).strip()
        return text or default

    def _read_primary_action(self, action_settings: Optional[dict]) -> str:
        value = self._read_str_setting(
            action_settings,
            "primary_action",
            DEFAULT_PRIMARY_ACTION,
        ).lower()
        if value in {"auto", "send_message", "create_order_candidate"}:
            return value
        return DEFAULT_PRIMARY_ACTION

    def _read_list_setting(
        self,
        action_settings: Optional[dict],
        key: str,
        default: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not isinstance(action_settings, dict):
            return tuple(default)
        raw_value = action_settings.get(key)
        if raw_value is None:
            return tuple(default)
        if isinstance(raw_value, str):
            return tuple(part.strip() for part in raw_value.split(",") if part.strip())
        if isinstance(raw_value, (list, tuple, set)):
            return tuple(str(part).strip() for part in raw_value if str(part).strip())
        return tuple(default)

    def _match_risk_words(
        self,
        record: dict,
        risk_words: tuple[str, ...],
    ) -> list[str]:
        item_info = record.get("商品信息", {}) or {}
        analysis_result = record.get("ai_analysis", {}) or {}
        text = " ".join(
            [
                str(item_info.get("商品标题") or ""),
                str(item_info.get("商品描述") or ""),
                str(item_info.get("商品链接") or ""),
                str(analysis_result.get("reason") or ""),
            ]
        ).lower()
        matched: list[str] = []
        for risk_word in risk_words:
            lowered = str(risk_word).strip().lower()
            if lowered and lowered in text:
                matched.append(str(risk_word))
        return matched

    def _merge_payload(self, payload: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        merged = dict(payload or {})
        merged.update(updates)
        return merged

    def _merge_risk_flags(
        self,
        left: tuple[str, ...],
        right: tuple[str, ...],
    ) -> list[str]:
        merged: list[str] = []
        seen = set()
        for item in list(left) + list(right):
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
        return merged

    def _log_event(self, event: str, action: Action, **extra) -> None:
        payload = {
            "event": event,
            "task_id": action.task_id,
            "item_id": action.item_id,
            "seller_id": action.seller_id,
            "action_type": action.action_type,
            "status": action.status,
            "error": action.last_error,
        }
        payload.update(extra)
        print("[ActionEngine] " + json.dumps(payload, ensure_ascii=False))
