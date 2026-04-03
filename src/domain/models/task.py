"""
任务领域模型
定义任务实体及其业务逻辑
"""
import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.cron_utils import validate_cron_expression
from src.services.account_strategy_service import (
    clean_account_state_file,
    normalize_account_strategy,
)


class TaskStatus(str, Enum):
    """任务状态枚举"""

    STOPPED = "stopped"
    RUNNING = "running"
    SCHEDULED = "scheduled"


def _normalize_keyword_values(value) -> List[str]:
    if value is None:
        return []

    raw_values = []
    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    elif isinstance(value, str):
        raw_values = re.split(r"[\n,]+", value)
    else:
        raw_values = [value]

    normalized: List[str] = []
    seen = set()
    for item in raw_values:
        text = str(item).strip()
        if not text:
            continue
        dedup_key = text.lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        normalized.append(text)
    return normalized


def _extract_keywords_from_legacy_groups(groups) -> List[str]:
    if not groups:
        return []

    merged: List[str] = []
    for group in groups:
        include_keywords = []
        if isinstance(group, dict):
            include_keywords = group.get("include_keywords") or []
        else:
            include_keywords = getattr(group, "include_keywords", []) or []
        merged.extend(_normalize_keyword_values(include_keywords))
    return _normalize_keyword_values(merged)


def _normalize_payload_keywords(payload: Any) -> Any:
    if payload is None or not isinstance(payload, dict):
        return payload
    values = dict(payload)
    values["account_state_file"] = clean_account_state_file(values.get("account_state_file"))
    values["account_strategy"] = normalize_account_strategy(
        values.get("account_strategy"),
        values.get("account_state_file"),
    )
    if "keyword_rules" in values:
        values["keyword_rules"] = _normalize_keyword_values(values.get("keyword_rules"))
    elif "keyword_rule_groups" in values:
        values["keyword_rules"] = _extract_keywords_from_legacy_groups(
            values.get("keyword_rule_groups")
        )
    return values


def _default_action_settings() -> Dict[str, Any]:
    return {
        "enabled": False,
        "primary_action": "auto",
        "message_template_id": "auto",
        "min_ai_score": 50,
        "seller_cooldown_seconds": 21600,
        "order_candidate_score_threshold": 75,
        "risk_words": [
            "私聊微信",
            "加微信",
            "vx",
            "v信",
            "先付定金",
            "付定金",
            "脱离平台",
            "线下交易",
            "QQ",
        ],
    }


def _default_vehicle_filter() -> Dict[str, Any]:
    return {}


def _normalize_action_settings(value: Any) -> Dict[str, Any]:
    default_settings = _default_action_settings()
    if value is None:
        return default_settings
    if isinstance(value, str):
        try:
            import json

            value = json.loads(value)
        except Exception:
            return default_settings
    if not isinstance(value, dict):
        return default_settings

    merged = dict(default_settings)
    merged.update(value)
    merged["enabled"] = bool(merged.get("enabled", False))
    primary_action = str(merged.get("primary_action", default_settings["primary_action"])).strip().lower()
    if primary_action not in {"auto", "send_message", "create_order_candidate"}:
        primary_action = default_settings["primary_action"]
    merged["primary_action"] = primary_action

    message_template_id = str(
        merged.get("message_template_id", default_settings["message_template_id"])
    ).strip()
    merged["message_template_id"] = message_template_id or default_settings["message_template_id"]
    for key in ("min_ai_score", "seller_cooldown_seconds", "order_candidate_score_threshold"):
        try:
            merged[key] = int(merged.get(key, default_settings[key]))
        except (TypeError, ValueError):
            merged[key] = default_settings[key]

    raw_risk_words = merged.get("risk_words", default_settings["risk_words"])
    if isinstance(raw_risk_words, str):
        merged["risk_words"] = [
            item.strip() for item in raw_risk_words.split(",") if item.strip()
        ]
    elif isinstance(raw_risk_words, (list, tuple, set)):
        merged["risk_words"] = [
            str(item).strip() for item in raw_risk_words if str(item).strip()
        ]
    else:
        merged["risk_words"] = list(default_settings["risk_words"])
    return merged


def _normalize_vehicle_filter(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            import json

            value = json.loads(value)
        except Exception:
            return {}
    if not isinstance(value, dict):
        return {}

    normalized: Dict[str, Any] = {}
    for key in ("series", "variant_keywords", "locations"):
        raw_value = value.get(key)
        if raw_value is None:
            continue
        normalized[key] = _normalize_keyword_values(raw_value)

    for key in ("mileage_km_min", "mileage_km_max", "transfer_count"):
        raw_value = value.get(key)
        if raw_value in (None, ""):
            continue
        try:
            normalized[key] = int(raw_value)
        except (TypeError, ValueError):
            continue

    for key in ("register_month_start", "register_month_end"):
        raw_value = _normalize_optional_string(value.get(key))
        if raw_value:
            normalized[key] = str(raw_value).strip()

    return normalized


def _has_keyword_rules(keyword_rules: List[str]) -> bool:
    return bool(keyword_rules and len(keyword_rules) > 0)


def _normalize_optional_string(value):
    if value == "" or value == "null" or value == "undefined" or value is None:
        return None
    return value


def _validate_cron_expression(value: Optional[str]) -> Optional[str]:
    return validate_cron_expression(value)


def _normalize_price_value(value):
    if _normalize_optional_string(value) is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return value


class Task(BaseModel):
    """任务实体"""

    model_config = ConfigDict(use_enum_values=True, extra="ignore")

    id: Optional[int] = None
    task_name: str
    enabled: bool
    keyword: str
    description: Optional[str] = ""
    analyze_images: bool = True
    max_pages: int
    personal_only: bool
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    cron: Optional[str] = None
    ai_prompt_base_file: str
    ai_prompt_criteria_file: str
    account_state_file: Optional[str] = None
    account_strategy: Literal["auto", "fixed", "rotate"] = "auto"
    free_shipping: bool = True
    new_publish_option: Optional[str] = None
    region: Optional[str] = None
    decision_mode: Literal["ai", "keyword"] = "ai"
    keyword_rules: List[str] = Field(default_factory=list)
    action_settings: Dict[str, Any] = Field(default_factory=_default_action_settings)
    enable_structured_prefilter: bool = False
    vehicle_filter: Dict[str, Any] = Field(default_factory=_default_vehicle_filter)
    is_running: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_keyword_payload(cls, values):
        return _normalize_payload_keywords(values)

    @field_validator("keyword_rules", mode="before")
    @classmethod
    def normalize_keyword_rules(cls, value):
        return _normalize_keyword_values(value)

    @field_validator("action_settings", mode="before")
    @classmethod
    def normalize_action_settings(cls, value):
        return _normalize_action_settings(value)

    @field_validator("vehicle_filter", mode="before")
    @classmethod
    def normalize_vehicle_filter(cls, value):
        return _normalize_vehicle_filter(value)

    def can_start(self) -> bool:
        """检查任务是否可以启动"""
        return self.enabled and not self.is_running

    def can_stop(self) -> bool:
        """检查任务是否可以停止"""
        return self.is_running

    def apply_update(self, update: "TaskUpdate") -> "Task":
        """应用更新并返回新的任务实例"""
        update_data = update.model_dump(exclude_unset=True)
        return self.model_copy(update=update_data)


class TaskCreate(BaseModel):
    """创建任务的DTO"""

    model_config = ConfigDict(extra="ignore")

    task_name: str
    enabled: bool = True
    keyword: str
    description: Optional[str] = ""
    analyze_images: bool = True
    max_pages: int = 3
    personal_only: bool = True
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    cron: Optional[str] = None
    ai_prompt_base_file: str = "prompts/base_prompt.txt"
    ai_prompt_criteria_file: str = ""
    account_state_file: Optional[str] = None
    account_strategy: Literal["auto", "fixed", "rotate"] = "auto"
    free_shipping: bool = True
    new_publish_option: Optional[str] = None
    region: Optional[str] = None
    decision_mode: Literal["ai", "keyword"] = "ai"
    keyword_rules: List[str] = Field(default_factory=list)
    action_settings: Dict[str, Any] = Field(default_factory=_default_action_settings)
    enable_structured_prefilter: bool = False
    vehicle_filter: Dict[str, Any] = Field(default_factory=_default_vehicle_filter)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_keyword_payload(cls, values):
        return _normalize_payload_keywords(values)

    @field_validator("min_price", "max_price", mode="before")
    @classmethod
    def convert_price_to_str(cls, value):
        return _normalize_price_value(value)

    @field_validator("cron", mode="before")
    @classmethod
    def normalize_cron(cls, value):
        return _normalize_optional_string(value)

    @field_validator("account_state_file", mode="before")
    @classmethod
    def normalize_account_state_file(cls, value):
        return clean_account_state_file(value)

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value):
        return _validate_cron_expression(value)

    @field_validator("keyword_rules", mode="before")
    @classmethod
    def normalize_keyword_rules(cls, value):
        return _normalize_keyword_values(value)

    @field_validator("action_settings", mode="before")
    @classmethod
    def normalize_action_settings(cls, value):
        return _normalize_action_settings(value)

    @field_validator("vehicle_filter", mode="before")
    @classmethod
    def normalize_vehicle_filter(cls, value):
        return _normalize_vehicle_filter(value)

    @model_validator(mode="after")
    def validate_decision_mode_payload(self):
        description = str(self.description or "").strip()
        if self.decision_mode == "ai" and not description:
            raise ValueError("AI 判断模式下，详细需求(description)不能为空。")
        if self.decision_mode == "keyword" and not _has_keyword_rules(self.keyword_rules):
            raise ValueError("关键词判断模式下，至少需要一个关键词。")
        if self.account_strategy == "fixed" and not self.account_state_file:
            raise ValueError("固定账号模式下必须选择账号。")
        return self


class TaskUpdate(BaseModel):
    """更新任务的DTO"""

    model_config = ConfigDict(extra="ignore")

    task_name: Optional[str] = None
    enabled: Optional[bool] = None
    keyword: Optional[str] = None
    description: Optional[str] = None
    analyze_images: Optional[bool] = None
    max_pages: Optional[int] = None
    personal_only: Optional[bool] = None
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    cron: Optional[str] = None
    ai_prompt_base_file: Optional[str] = None
    ai_prompt_criteria_file: Optional[str] = None
    account_state_file: Optional[str] = None
    account_strategy: Optional[Literal["auto", "fixed", "rotate"]] = None
    free_shipping: Optional[bool] = None
    new_publish_option: Optional[str] = None
    region: Optional[str] = None
    decision_mode: Optional[Literal["ai", "keyword"]] = None
    keyword_rules: Optional[List[str]] = None
    action_settings: Optional[Dict[str, Any]] = None
    enable_structured_prefilter: Optional[bool] = None
    vehicle_filter: Optional[Dict[str, Any]] = None
    is_running: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_keyword_payload(cls, values):
        return _normalize_payload_keywords(values)

    @field_validator("min_price", "max_price", mode="before")
    @classmethod
    def convert_price_to_str(cls, value):
        return _normalize_price_value(value)

    @field_validator("cron", mode="before")
    @classmethod
    def normalize_cron(cls, value):
        return _normalize_optional_string(value)

    @field_validator("account_state_file", mode="before")
    @classmethod
    def normalize_account_state_file(cls, value):
        return clean_account_state_file(value)

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value):
        return _validate_cron_expression(value)

    @field_validator("keyword_rules", mode="before")
    @classmethod
    def normalize_keyword_rules(cls, value):
        return _normalize_keyword_values(value)

    @field_validator("action_settings", mode="before")
    @classmethod
    def normalize_action_settings(cls, value):
        if value is None:
            return None
        return _normalize_action_settings(value)

    @field_validator("vehicle_filter", mode="before")
    @classmethod
    def normalize_vehicle_filter(cls, value):
        if value is None:
            return None
        return _normalize_vehicle_filter(value)

    @model_validator(mode="after")
    def validate_partial_keyword_payload(self):
        if self.decision_mode == "keyword" and self.keyword_rules is not None:
            if not _has_keyword_rules(self.keyword_rules):
                raise ValueError("关键词判断模式下，至少需要一个关键词。")
        if self.decision_mode == "ai" and self.description is not None:
            if not str(self.description).strip():
                raise ValueError("AI 判断模式下，详细需求(description)不能为空。")
        return self


class TaskGenerateRequest(BaseModel):
    """任务创建请求DTO（AI模式支持自动生成标准）"""

    model_config = ConfigDict(extra="ignore")

    task_name: str
    keyword: str
    description: Optional[str] = ""
    analyze_images: bool = True
    personal_only: bool = True
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    max_pages: int = 3
    cron: Optional[str] = None
    account_state_file: Optional[str] = None
    account_strategy: Literal["auto", "fixed", "rotate"] = "auto"
    free_shipping: bool = True
    new_publish_option: Optional[str] = None
    region: Optional[str] = None
    decision_mode: Literal["ai", "keyword"] = "ai"
    keyword_rules: List[str] = Field(default_factory=list)
    action_settings: Dict[str, Any] = Field(default_factory=_default_action_settings)
    enable_structured_prefilter: bool = False
    vehicle_filter: Dict[str, Any] = Field(default_factory=_default_vehicle_filter)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_keyword_payload(cls, values):
        return _normalize_payload_keywords(values)

    @field_validator("min_price", "max_price", mode="before")
    @classmethod
    def convert_price_to_str(cls, value):
        return _normalize_price_value(value)

    @field_validator("cron", mode="before")
    @classmethod
    def empty_str_to_none(cls, value):
        return _normalize_optional_string(value)

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value):
        return _validate_cron_expression(value)

    @field_validator("account_state_file", mode="before")
    @classmethod
    def empty_account_to_none(cls, value):
        return _normalize_optional_string(value)

    @field_validator("new_publish_option", "region", mode="before")
    @classmethod
    def empty_str_to_none_for_strings(cls, value):
        return _normalize_optional_string(value)

    @field_validator("keyword_rules", mode="before")
    @classmethod
    def normalize_keyword_rules(cls, value):
        return _normalize_keyword_values(value)

    @field_validator("action_settings", mode="before")
    @classmethod
    def normalize_action_settings(cls, value):
        return _normalize_action_settings(value)

    @field_validator("vehicle_filter", mode="before")
    @classmethod
    def normalize_vehicle_filter(cls, value):
        return _normalize_vehicle_filter(value)

    @model_validator(mode="after")
    def validate_decision_mode_payload(self):
        description = str(self.description or "").strip()
        if self.decision_mode == "ai" and not description:
            raise ValueError("AI 判断模式下，详细需求(description)不能为空。")
        if self.decision_mode == "keyword" and not _has_keyword_rules(self.keyword_rules):
            raise ValueError("关键词判断模式下，至少需要一个关键词。")
        if self.account_strategy == "fixed" and not self.account_state_file:
            raise ValueError("固定账号模式下必须选择账号。")
        return self
