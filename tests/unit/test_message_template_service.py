from src.services.message_template_service import MessageTemplateService


def test_message_template_service_selects_battery_template():
    service = MessageTemplateService()

    template_id = service.choose_template_id(
        item_info={"商品标题": "iPhone 15 Pro Max 电池 89%"},
        analysis_result={"reason": "需要确认电池健康情况", "risk_tags": []},
    )

    assert template_id == "ask_battery"
    assert "续航" in service.render_template(template_id)


def test_message_template_service_falls_back_to_availability():
    service = MessageTemplateService()

    template_id = service.choose_template_id(
        item_info={"商品标题": "索尼 A7M4 单机身"},
        analysis_result={"reason": "整体条件满足，可先确认是否仍在售", "risk_tags": []},
    )

    assert template_id == "ask_availability"
    assert service.render_template(template_id) == "你好，请问这个还在吗？"


def test_message_template_service_respects_configured_template():
    service = MessageTemplateService()

    template_id = service.resolve_template_id(
        configured_template_id="ask_lowest_price",
        item_info={"商品标题": "索尼 A7M4 单机身"},
        analysis_result={"reason": "希望先问最低价", "risk_tags": []},
    )

    assert template_id == "ask_lowest_price"
    assert service.render_template(template_id) == "我想要你这个商品最低价多钱？"
