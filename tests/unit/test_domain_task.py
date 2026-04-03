from src.domain.models.task import Task, TaskGenerateRequest, TaskUpdate


def test_task_can_start_and_stop():
    task = Task(
        id=1,
        task_name="Sony A7M4",
        enabled=True,
        keyword="sony a7m4",
        description="body",
        max_pages=2,
        personal_only=True,
        min_price=None,
        max_price=None,
        cron=None,
        ai_prompt_base_file="prompts/base_prompt.txt",
        ai_prompt_criteria_file="prompts/sony_a7m4_criteria.txt",
        is_running=False,
    )

    assert task.can_start() is True
    assert task.can_stop() is False

    running = task.model_copy(update={"is_running": True})
    assert running.can_start() is False
    assert running.can_stop() is True


def test_task_apply_update():
    task = Task(
        id=1,
        task_name="Sony A7M4",
        enabled=True,
        keyword="sony a7m4",
        description="body",
        max_pages=2,
        personal_only=True,
        min_price=None,
        max_price=None,
        cron=None,
        ai_prompt_base_file="prompts/base_prompt.txt",
        ai_prompt_criteria_file="prompts/sony_a7m4_criteria.txt",
        is_running=False,
    )

    update = TaskUpdate(enabled=False, max_pages=5)
    updated = task.apply_update(update)

    assert updated.enabled is False
    assert updated.max_pages == 5
    assert updated.task_name == task.task_name


def test_legacy_keyword_groups_are_flattened_to_keyword_rules():
    task = Task(
        id=1,
        task_name="Sony A7M4",
        enabled=True,
        keyword="sony a7m4",
        description="body",
        max_pages=2,
        personal_only=True,
        min_price=None,
        max_price=None,
        cron=None,
        ai_prompt_base_file="prompts/base_prompt.txt",
        ai_prompt_criteria_file="prompts/sony_a7m4_criteria.txt",
        decision_mode="keyword",
        keyword_rule_groups=[
            {"name": "组1", "include_keywords": ["a7m4", "验货宝"], "exclude_keywords": ["瑕疵"]},
            {"name": "组2", "include_keywords": ["全画幅", "a7m4"], "exclude_keywords": ["拆修"]},
        ],
        is_running=False,
    )

    assert task.keyword_rules == ["a7m4", "验货宝", "全画幅"]


def test_generate_request_accepts_legacy_group_payload():
    req = TaskGenerateRequest(
        task_name="legacy",
        keyword="sony a7m4",
        description="",
        decision_mode="keyword",
        keyword_rule_groups=[{"include_keywords": ["a7m4", "验货宝"], "exclude_keywords": ["瑕疵"]}],
    )
    assert req.keyword_rules == ["a7m4", "验货宝"]


def test_generate_request_enables_image_analysis_by_default():
    req = TaskGenerateRequest(
        task_name="Sony A7M4",
        keyword="sony a7m4",
        description="只看机身成色和卖家信用。",
        decision_mode="ai",
    )
    assert req.analyze_images is True


def test_generate_request_infers_fixed_account_strategy_from_state_file():
    req = TaskGenerateRequest(
        task_name="Sony A7M4",
        keyword="sony a7m4",
        description="只看机身成色和卖家信用。",
        decision_mode="ai",
        account_state_file="state/acc_1.json",
    )

    assert req.account_strategy == "fixed"


def test_generate_request_requires_state_file_for_fixed_account_strategy():
    try:
        TaskGenerateRequest(
            task_name="Sony A7M4",
            keyword="sony a7m4",
            description="只看机身成色和卖家信用。",
            decision_mode="ai",
            account_strategy="fixed",
        )
    except ValueError as exc:
        assert "固定账号模式下必须选择账号" in str(exc)
        return

    raise AssertionError("固定账号模式应要求 account_state_file")


def test_generate_request_normalizes_action_settings_with_fixed_template():
    req = TaskGenerateRequest(
        task_name="Sony A7M4",
        keyword="sony a7m4",
        description="先询问卖家底价。",
        decision_mode="ai",
        action_settings={
            "enabled": True,
            "primary_action": "send_message",
            "message_template_id": "ask_lowest_price",
            "risk_words": "私聊微信,先付定金",
        },
    )

    assert req.action_settings["enabled"] is True
    assert req.action_settings["primary_action"] == "send_message"
    assert req.action_settings["message_template_id"] == "ask_lowest_price"
    assert req.action_settings["risk_words"] == ["私聊微信", "先付定金"]


def test_generate_request_normalizes_vehicle_filter():
    req = TaskGenerateRequest(
        task_name="Tesla Model Y",
        keyword="model y",
        description="优先看平台结构化字段。",
        decision_mode="ai",
        enable_structured_prefilter=True,
        vehicle_filter={
            "series": "Model Y,Model Y",
            "variant_keywords": "2024款,后轮驱动,纯电动",
            "mileage_km_min": "10000",
            "mileage_km_max": "35000",
            "transfer_count": "0",
            "locations": "四川,重庆",
            "register_month_start": "2024-09",
            "register_month_end": "2025-03",
        },
    )

    assert req.enable_structured_prefilter is True
    assert req.vehicle_filter["series"] == ["Model Y"]
    assert req.vehicle_filter["variant_keywords"] == ["2024款", "后轮驱动", "纯电动"]
    assert req.vehicle_filter["locations"] == ["四川", "重庆"]
    assert req.vehicle_filter["mileage_km_min"] == 10000
    assert req.vehicle_filter["mileage_km_max"] == 35000
    assert req.vehicle_filter["transfer_count"] == 0
