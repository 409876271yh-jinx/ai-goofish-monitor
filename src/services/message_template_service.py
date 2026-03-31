"""
首条消息模板服务
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional


DEFAULT_MESSAGE_TEMPLATES: dict[str, str] = {
    "ask_availability": "你好，请问这个还在吗？",
    "ask_condition": "你好，请问成色和是否有维修/暗病方便描述一下吗？",
    "ask_battery": "你好，请问电池健康/续航情况怎么样？",
    "ask_lowest_price": "我想要你这个商品最低价多钱？",
}

BATTERY_HINTS = (
    "电池",
    "续航",
    "battery",
    "健康",
)
CONDITION_HINTS = (
    "成色",
    "维修",
    "暗病",
    "磕碰",
    "划痕",
    "拆修",
    "翻新",
)


class MessageTemplateService:
    """受白名单控制的消息模板选择器"""

    def __init__(self, templates: Optional[dict[str, str]] = None) -> None:
        self._templates = dict(DEFAULT_MESSAGE_TEMPLATES)
        if templates:
            self._templates.update(templates)

    def list_templates(self) -> dict[str, str]:
        return dict(self._templates)

    def get_template(self, template_id: str) -> Optional[str]:
        return self._templates.get(template_id)

    def has_template(self, template_id: str) -> bool:
        return template_id in self._templates

    def render_template(
        self,
        template_id: str,
        variables: Optional[dict[str, str]] = None,
    ) -> str:
        template = self.get_template(template_id)
        if template is None:
            raise ValueError(f"未知消息模板: {template_id}")
        return template.format(**(variables or {}))

    def resolve_template_id(
        self,
        *,
        configured_template_id: Optional[str],
        item_info: dict,
        analysis_result: dict,
    ) -> str:
        configured_value = str(configured_template_id or "").strip()
        if configured_value and configured_value.lower() != "auto" and self.has_template(configured_value):
            return configured_value
        return self.choose_template_id(
            item_info=item_info,
            analysis_result=analysis_result,
        )

    def choose_template_id(
        self,
        *,
        item_info: dict,
        analysis_result: dict,
    ) -> str:
        text_parts = [
            str(item_info.get("商品标题") or ""),
            str(item_info.get("商品描述") or ""),
            str(analysis_result.get("reason") or ""),
        ]
        text_parts.extend(str(value) for value in analysis_result.get("risk_tags") or [])
        combined_text = " ".join(text_parts).lower()

        if self._contains_any(combined_text, BATTERY_HINTS):
            return "ask_battery"
        if self._contains_any(combined_text, CONDITION_HINTS):
            return "ask_condition"
        return "ask_availability"

    def _contains_any(self, text: str, keywords: Iterable[str]) -> bool:
        lowered = str(text or "").lower()
        return any(str(keyword).lower() in lowered for keyword in keywords)
