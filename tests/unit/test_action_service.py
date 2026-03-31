from __future__ import annotations

import asyncio
from datetime import datetime

from src.infrastructure.executors.browser_executor import BrowserActionResult
from src.infrastructure.persistence.sqlite_action_repository import SqliteActionRepository
from src.services.action_service import ActionService


class _FakeNotificationService:
    def __init__(self):
        self.messages = []

    async def send_notification(self, product_data, reason):
        self.messages.append((product_data, reason))
        return {
            "fake": {
                "channel": "fake",
                "label": "Fake",
                "success": True,
                "message": "ok",
            }
        }


class _FakeBrowserExecutor:
    def __init__(self, result: BrowserActionResult):
        self.result = result
        self.calls = []

    async def send_message(self, item_url, message, login_state, *, timeout_ms=15000):
        self.calls.append(
            {
                "item_url": item_url,
                "message": message,
                "login_state": login_state,
                "timeout_ms": timeout_ms,
            }
        )
        return self.result


def _build_record(
    *,
    item_id: str,
    title: str = "Sony A7M4",
    price: str = "9999",
    link: str = "https://www.goofish.com/item?id=123",
    value_score: int = 55,
    reason: str = "成色不错，但还需要进一步确认细节",
    risk_tags: list[str] | None = None,
):
    analysis = {
        "analysis_source": "ai",
        "is_recommended": True,
        "reason": reason,
        "risk_tags": risk_tags or [],
        "value_score": value_score,
    }
    return {
        "任务名称": "Demo Task",
        "商品信息": {
            "商品ID": item_id,
            "商品标题": title,
            "当前售价": price,
            "商品链接": link,
        },
        "卖家信息": {
            "卖家昵称": "seller-demo",
        },
        "ai_analysis": analysis,
        "price_insight": {"deal_score": value_score},
    }, analysis


def test_action_service_builds_order_candidate_decision(tmp_path):
    record, analysis = _build_record(
        item_id="item-1",
        value_score=88,
        reason="价格明显低于市场均价，值得优先跟进",
    )
    service = ActionService(
        SqliteActionRepository(
            db_path=str(tmp_path / "app.sqlite3"),
            legacy_config_file=None,
        ),
        notification_service=_FakeNotificationService(),
        browser_executor_factory=lambda: _FakeBrowserExecutor(
            BrowserActionResult(success=True, status="success")
        ),
    )

    decision = service.build_action_decision(record=record, analysis_result=analysis)

    assert decision.to_dict()["action_type"] == "create_order_candidate"
    assert decision.to_dict()["should_act"] is True


def test_action_service_respects_forced_message_template(tmp_path):
    record, analysis = _build_record(
        item_id="item-force-message",
        value_score=90,
        reason="先沟通确认卖家愿意让价，再决定是否继续跟进",
    )
    service = ActionService(
        SqliteActionRepository(
            db_path=str(tmp_path / "app.sqlite3"),
            legacy_config_file=None,
        ),
        notification_service=_FakeNotificationService(),
        browser_executor_factory=lambda: _FakeBrowserExecutor(
            BrowserActionResult(success=True, status="success")
        ),
    )

    decision = service.build_action_decision(
        record=record,
        analysis_result=analysis,
        action_settings={
            "primary_action": "send_message",
            "message_template_id": "ask_lowest_price",
        },
    )

    assert decision.to_dict()["action_type"] == "send_message"
    assert decision.to_dict()["template_id"] == "ask_lowest_price"
    assert decision.to_dict()["should_act"] is True


def test_action_service_enforces_idempotency(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    notifications = _FakeNotificationService()
    service = ActionService(
        SqliteActionRepository(db_path=str(db_path), legacy_config_file=None),
        notification_service=notifications,
        browser_executor_factory=lambda: _FakeBrowserExecutor(
            BrowserActionResult(success=True, status="success")
        ),
        now_provider=lambda: datetime(2026, 3, 31, 12, 0, 0),
    )
    record, analysis = _build_record(
        item_id="dup-1",
        value_score=92,
        reason="价格非常好，适合生成候选下单",
    )

    async def run():
        first = await service.handle_recommended_item(
            task_id=1,
            task_name="Demo Task",
            record=record,
            analysis_result=analysis,
            login_state_path=None,
            seller_id="seller-1",
        )
        second = await service.handle_recommended_item(
            task_id=1,
            task_name="Demo Task",
            record=record,
            analysis_result=analysis,
            login_state_path=None,
            seller_id="seller-1",
        )
        return first, second

    first_action, second_action = asyncio.run(run())

    assert first_action.action_type == "create_order_candidate"
    assert first_action.status == "success"
    assert second_action.action_type == "skip"
    assert second_action.status == "cancelled"
    assert "幂等保护" in second_action.last_error


def test_action_service_enforces_seller_cooldown(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    notifications = _FakeNotificationService()
    executor = _FakeBrowserExecutor(BrowserActionResult(success=True, status="success"))
    fixed_now = datetime(2026, 3, 31, 12, 0, 0)
    service = ActionService(
        SqliteActionRepository(db_path=str(db_path), legacy_config_file=None),
        notification_service=notifications,
        browser_executor_factory=lambda: executor,
        now_provider=lambda: fixed_now,
    )

    first_record, first_analysis = _build_record(
        item_id="msg-1",
        title="Sony A7M4 单机",
        value_score=55,
    )
    second_record, second_analysis = _build_record(
        item_id="msg-2",
        title="Sony A7M4 套机",
        link="https://www.goofish.com/item?id=456",
        value_score=58,
    )

    async def run():
        first = await service.handle_recommended_item(
            task_id=2,
            task_name="Demo Task",
            record=first_record,
            analysis_result=first_analysis,
            login_state_path="state/demo.json",
            seller_id="seller-1",
        )
        second = await service.handle_recommended_item(
            task_id=2,
            task_name="Demo Task",
            record=second_record,
            analysis_result=second_analysis,
            login_state_path="state/demo.json",
            seller_id="seller-1",
        )
        return first, second

    first_action, second_action = asyncio.run(run())

    assert first_action.action_type == "send_message"
    assert first_action.status == "success"
    assert second_action.action_type == "skip"
    assert second_action.status == "cancelled"
    assert "冷却期" in second_action.last_error
    assert len(executor.calls) == 1


def test_action_service_send_message_failure_does_not_raise(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    notifications = _FakeNotificationService()
    executor = _FakeBrowserExecutor(
        BrowserActionResult(
            success=False,
            status="selector_error",
            error="message_input_not_found",
            detail="未定位到消息输入框",
        )
    )
    service = ActionService(
        SqliteActionRepository(db_path=str(db_path), legacy_config_file=None),
        notification_service=notifications,
        browser_executor_factory=lambda: executor,
        now_provider=lambda: datetime(2026, 3, 31, 12, 0, 0),
    )
    record, analysis = _build_record(
        item_id="msg-fail-1",
        title="iPhone 15 Pro Max 电池 89%",
        reason="需要进一步确认电池健康情况",
        value_score=52,
    )

    action = asyncio.run(
        service.handle_recommended_item(
            task_id=3,
            task_name="Battery Task",
            record=record,
            analysis_result=analysis,
            login_state_path="state/demo.json",
            seller_id="seller-battery",
        )
    )

    assert action.action_type == "send_message"
    assert action.status == "failed"
    assert "未定位到消息输入框" in action.last_error
    assert len(notifications.messages) == 1


def test_action_service_uses_forced_lowest_price_template_on_send(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    notifications = _FakeNotificationService()
    executor = _FakeBrowserExecutor(BrowserActionResult(success=True, status="success"))
    service = ActionService(
        SqliteActionRepository(db_path=str(db_path), legacy_config_file=None),
        notification_service=notifications,
        browser_executor_factory=lambda: executor,
        now_provider=lambda: datetime(2026, 3, 31, 12, 0, 0),
    )
    record, analysis = _build_record(
        item_id="msg-lowest-price-1",
        title="Sony A7M4 单机",
        value_score=88,
        reason="先沟通底价，再由人工判断是否继续。",
    )

    action = asyncio.run(
        service.handle_recommended_item(
            task_id=4,
            task_name="Lowest Price Task",
            record=record,
            analysis_result=analysis,
            login_state_path="state/demo.json",
            seller_id="seller-lowest-price",
            action_settings={
                "enabled": True,
                "primary_action": "send_message",
                "message_template_id": "ask_lowest_price",
                "min_ai_score": 50,
                "seller_cooldown_seconds": 21600,
                "order_candidate_score_threshold": 75,
                "risk_words": [],
            },
        )
    )

    assert action.action_type == "send_message"
    assert action.status == "success"
    assert executor.calls[0]["message"] == "我想要你这个商品最低价多钱？"
