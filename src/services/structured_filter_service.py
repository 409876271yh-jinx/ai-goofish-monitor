"""
结构化字段预筛选服务。

仅依赖闲鱼页面中可提取的结构化字段，不以卖家自由文本描述作为硬规则判断依据。
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional


STRUCTURED_FILTER_ANALYSIS_SOURCE = "structured_filter"

PASS_STATUS = "pass"
FAIL_STATUS = "fail"
UNKNOWN_STATUS = "unknown"
NOT_APPLICABLE_STATUS = "not_applicable"


SERIES_LABEL_HINTS = (
    "车系",
    "系列",
    "车系名称",
)
SERIES_KEY_HINTS = (
    "series",
    "seriesname",
    "carseries",
    "vehicleseries",
)
VARIANT_LABEL_HINTS = (
    "车型",
    "车型版本",
    "版本",
    "配置",
    "车款",
    "款型",
    "动力类型",
    "驱动方式",
    "能源类型",
    "燃料类型",
    "变速箱",
)
VARIANT_KEY_HINTS = (
    "variant",
    "model",
    "version",
    "trim",
    "trimname",
    "cartype",
    "vehiclemodel",
    "drivemode",
    "fueltype",
    "energytype",
)
MILEAGE_LABEL_HINTS = (
    "表显里程",
    "里程",
    "里程数",
    "行驶里程",
    "公里数",
)
MILEAGE_KEY_HINTS = (
    "mileage",
    "mile",
    "odometer",
    "distance",
)
TRANSFER_LABEL_HINTS = (
    "过户次数",
    "过户",
    "转手次数",
)
TRANSFER_KEY_HINTS = (
    "transfercount",
    "transfercnt",
    "transfer",
)
LOCATION_LABEL_HINTS = (
    "车源地",
    "所在地",
    "看车城市",
    "所在城市",
    "地区",
    "发货地区",
)
LOCATION_KEY_HINTS = (
    "location",
    "locationtext",
    "province",
    "city",
    "sourcecity",
    "carsourcelocation",
)
REGISTER_LABEL_HINTS = (
    "上牌时间",
    "上牌年月",
    "首次上牌",
    "首次上牌时间",
    "上牌日期",
)
REGISTER_KEY_HINTS = (
    "registermonth",
    "registerdate",
    "licensetime",
    "licensedate",
    "firstregisterdate",
)

GENERIC_LABEL_KEYS = (
    "name",
    "label",
    "title",
    "key",
    "attrName",
    "propName",
    "displayName",
)
GENERIC_VALUE_KEYS = (
    "value",
    "text",
    "content",
    "displayValue",
    "desc",
    "labelText",
)

LOCATION_PREFIXES = (
    "北京",
    "上海",
    "天津",
    "重庆",
    "河北",
    "山西",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "海南",
    "四川",
    "贵州",
    "云南",
    "陕西",
    "甘肃",
    "青海",
    "台湾",
    "内蒙古",
    "广西",
    "西藏",
    "宁夏",
    "新疆",
    "香港",
    "澳门",
)

CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def normalize_series(text: Any) -> Optional[str]:
    value = _clean_text(text)
    if not value:
        return None
    lowered = re.sub(r"\s+", "", value).lower()
    if "modely" in lowered:
        return "Model Y"
    if "model3" in lowered:
        return "Model 3"
    if "modelx" in lowered:
        return "Model X"
    if "models" in lowered:
        return "Model S"
    return re.sub(r"\s+", " ", value).strip()


def normalize_variant(text: Any) -> Optional[str]:
    value = _clean_text(text)
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()


def parse_mileage_km(value: Any) -> Optional[int]:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace(",", "").replace("，", "")
    range_match = re.search(
        r"(\d+(?:\.\d+)?)(万?)\s*[-~至]\s*(\d+(?:\.\d+)?)(万?)",
        normalized,
    )
    if range_match:
        upper_value = float(range_match.group(3))
        if "万" in (range_match.group(2) + range_match.group(4)):
            upper_value *= 10000
        return int(round(upper_value))

    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return None
    number = float(match.group(1))
    if "万" in normalized:
        number *= 10000
    return int(round(number))


def parse_transfer_count(value: Any) -> Optional[int]:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace(" ", "")
    if "未过户" in normalized or "0次过户" in normalized or "零次过户" in normalized:
        return 0
    if "一手" in normalized and "过户" not in normalized:
        return 0
    digit_match = re.search(r"(\d+)", normalized)
    if digit_match:
        return int(digit_match.group(1))
    chinese_match = re.search(r"(零|〇|一|二|两|三|四|五|六|七|八|九|十)次", normalized)
    if chinese_match:
        return _parse_chinese_digit(chinese_match.group(1))
    return None


def parse_register_month(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    match = re.search(r"(\d{4})\D+(\d{1,2})", text)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    if year < 1900 or month < 1 or month > 12:
        return None
    return f"{year:04d}-{month:02d}"


def parse_location(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    for prefix in LOCATION_PREFIXES:
        if compact.startswith(prefix):
            return prefix
    for prefix in LOCATION_PREFIXES:
        if prefix in compact:
            return prefix
    return compact


def normalize_vehicle_filter_config(value: Any) -> dict[str, Any]:
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

    config: dict[str, Any] = {}
    config["series"] = _normalize_string_list(value.get("series"), normalize_series)
    config["variant_keywords"] = _normalize_string_list(value.get("variant_keywords"))
    config["locations"] = _normalize_string_list(value.get("locations"), parse_location)
    config["mileage_km_min"] = _coerce_int_or_none(value.get("mileage_km_min"))
    config["mileage_km_max"] = _coerce_int_or_none(value.get("mileage_km_max"))
    config["transfer_count"] = _coerce_int_or_none(value.get("transfer_count"))
    config["register_month_start"] = parse_register_month(value.get("register_month_start"))
    config["register_month_end"] = parse_register_month(value.get("register_month_end"))

    return {key: item for key, item in config.items() if item not in (None, [], {})}


def extract_vehicle_structured_fields(
    record: dict,
    detail_payload: Optional[dict] = None,
) -> dict[str, Any]:
    item_info = record.get("商品信息", {}) or {}
    detail_payload = detail_payload or {}
    platform_pairs = _collect_vehicle_property_pairs(detail_payload)
    item_do = ((detail_payload.get("data") or {}).get("itemDO") or {})
    if platform_pairs:
        structured_pairs = platform_pairs
        scalar_pairs: list[tuple[str, str]] = []
    else:
        structured_pairs = _collect_named_pairs(item_do)
        scalar_pairs = _collect_scalar_pairs(item_do)

    series_raw = _first_match(structured_pairs, scalar_pairs, SERIES_LABEL_HINTS, SERIES_KEY_HINTS)
    mileage_raw = _first_match(structured_pairs, scalar_pairs, MILEAGE_LABEL_HINTS, MILEAGE_KEY_HINTS)
    transfer_raw = _first_match(structured_pairs, scalar_pairs, TRANSFER_LABEL_HINTS, TRANSFER_KEY_HINTS)
    register_raw = _first_match(structured_pairs, scalar_pairs, REGISTER_LABEL_HINTS, REGISTER_KEY_HINTS)
    location_raw = _first_match(structured_pairs, scalar_pairs, LOCATION_LABEL_HINTS, LOCATION_KEY_HINTS)
    if not location_raw:
        location_raw = item_info.get("发货地区")

    variant_components = _collect_matches(
        structured_pairs,
        scalar_pairs,
        SERIES_LABEL_HINTS + VARIANT_LABEL_HINTS,
        SERIES_KEY_HINTS + VARIANT_KEY_HINTS,
    )
    variant_text = normalize_variant(" ".join(_dedupe_preserve_order(variant_components)))

    series = normalize_series(series_raw)
    if not series and variant_text:
        series = normalize_series(variant_text)

    return {
        "series": series,
        "variant_text": variant_text,
        "mileage_km": parse_mileage_km(mileage_raw),
        "transfer_count": parse_transfer_count(transfer_raw),
        "location": parse_location(location_raw),
        "register_month": parse_register_month(register_raw),
    }


class StructuredFilterService:
    """基于平台结构化字段的硬规则预筛选。"""

    def evaluate_vehicle_filter(
        self,
        *,
        record: dict,
        detail_payload: Optional[dict],
        vehicle_filter: Optional[dict],
    ) -> dict[str, Any]:
        config = normalize_vehicle_filter_config(vehicle_filter)
        normalized_fields = extract_vehicle_structured_fields(record, detail_payload)

        checks = {
            "series": NOT_APPLICABLE_STATUS,
            "variant": NOT_APPLICABLE_STATUS,
            "mileage": NOT_APPLICABLE_STATUS,
            "transfer_count": NOT_APPLICABLE_STATUS,
            "location": NOT_APPLICABLE_STATUS,
            "register_date": NOT_APPLICABLE_STATUS,
        }
        failure_reasons: list[str] = []
        unknown_fields: list[str] = []

        self._evaluate_series(config, normalized_fields, checks, failure_reasons, unknown_fields)
        self._evaluate_variant(config, normalized_fields, checks, failure_reasons, unknown_fields)
        self._evaluate_mileage(config, normalized_fields, checks, failure_reasons, unknown_fields)
        self._evaluate_transfer_count(config, normalized_fields, checks, failure_reasons, unknown_fields)
        self._evaluate_location(config, normalized_fields, checks, failure_reasons, unknown_fields)
        self._evaluate_register_month(config, normalized_fields, checks, failure_reasons, unknown_fields)

        if failure_reasons:
            reason = "；".join(failure_reasons)
            passed = False
        elif unknown_fields:
            reason = "结构化字段未发现明确冲突，但以下字段缺失或无法解析: " + "、".join(unknown_fields)
            passed = True
        elif config:
            reason = "结构化字段全部满足"
            passed = True
        else:
            reason = "未配置 vehicle_filter，跳过结构化字段过滤"
            passed = True

        return {
            "passed": passed,
            "reason": reason,
            "checks": checks,
            "normalized_fields": normalized_fields,
        }

    def _evaluate_series(
        self,
        config: dict[str, Any],
        normalized_fields: dict[str, Any],
        checks: dict[str, str],
        failure_reasons: list[str],
        unknown_fields: list[str],
    ) -> None:
        allowed_series = config.get("series") or []
        if not allowed_series:
            return
        series = normalized_fields.get("series")
        if not series:
            checks["series"] = UNKNOWN_STATUS
            unknown_fields.append("series")
            return
        if series in allowed_series:
            checks["series"] = PASS_STATUS
            return
        checks["series"] = FAIL_STATUS
        failure_reasons.append(f"车系不匹配: {series}")

    def _evaluate_variant(
        self,
        config: dict[str, Any],
        normalized_fields: dict[str, Any],
        checks: dict[str, str],
        failure_reasons: list[str],
        unknown_fields: list[str],
    ) -> None:
        required_keywords = [str(item).strip() for item in config.get("variant_keywords") or [] if str(item).strip()]
        if not required_keywords:
            return
        variant_text = normalized_fields.get("variant_text")
        if not variant_text:
            checks["variant"] = UNKNOWN_STATUS
            unknown_fields.append("variant")
            return
        lowered = variant_text.lower()
        missing = [keyword for keyword in required_keywords if keyword.lower() not in lowered]
        if not missing:
            checks["variant"] = PASS_STATUS
            return
        checks["variant"] = FAIL_STATUS
        failure_reasons.append("车型/版本字段不匹配: 缺少 " + ", ".join(missing))

    def _evaluate_mileage(
        self,
        config: dict[str, Any],
        normalized_fields: dict[str, Any],
        checks: dict[str, str],
        failure_reasons: list[str],
        unknown_fields: list[str],
    ) -> None:
        mileage_min = config.get("mileage_km_min")
        mileage_max = config.get("mileage_km_max")
        if mileage_min is None and mileage_max is None:
            return
        mileage_km = normalized_fields.get("mileage_km")
        if mileage_km is None:
            checks["mileage"] = UNKNOWN_STATUS
            unknown_fields.append("mileage")
            return
        if mileage_min is not None and mileage_km < mileage_min:
            checks["mileage"] = FAIL_STATUS
            failure_reasons.append(f"里程过低: {mileage_km}km")
            return
        if mileage_max is not None and mileage_km > mileage_max:
            checks["mileage"] = FAIL_STATUS
            failure_reasons.append(f"里程过高: {mileage_km}km")
            return
        checks["mileage"] = PASS_STATUS

    def _evaluate_transfer_count(
        self,
        config: dict[str, Any],
        normalized_fields: dict[str, Any],
        checks: dict[str, str],
        failure_reasons: list[str],
        unknown_fields: list[str],
    ) -> None:
        expected = config.get("transfer_count")
        if expected is None:
            return
        actual = normalized_fields.get("transfer_count")
        if actual is None:
            checks["transfer_count"] = UNKNOWN_STATUS
            unknown_fields.append("transfer_count")
            return
        if actual == expected:
            checks["transfer_count"] = PASS_STATUS
            return
        checks["transfer_count"] = FAIL_STATUS
        failure_reasons.append(f"过户次数不匹配: {actual}")

    def _evaluate_location(
        self,
        config: dict[str, Any],
        normalized_fields: dict[str, Any],
        checks: dict[str, str],
        failure_reasons: list[str],
        unknown_fields: list[str],
    ) -> None:
        allowed_locations = config.get("locations") or []
        if not allowed_locations:
            return
        location = normalized_fields.get("location")
        if not location:
            checks["location"] = UNKNOWN_STATUS
            unknown_fields.append("location")
            return
        if location in allowed_locations:
            checks["location"] = PASS_STATUS
            return
        checks["location"] = FAIL_STATUS
        failure_reasons.append(f"地区不匹配: {location}")

    def _evaluate_register_month(
        self,
        config: dict[str, Any],
        normalized_fields: dict[str, Any],
        checks: dict[str, str],
        failure_reasons: list[str],
        unknown_fields: list[str],
    ) -> None:
        start = config.get("register_month_start")
        end = config.get("register_month_end")
        if not start and not end:
            return
        register_month = normalized_fields.get("register_month")
        if not register_month:
            checks["register_date"] = UNKNOWN_STATUS
            unknown_fields.append("register_date")
            return
        if start and register_month < start:
            checks["register_date"] = FAIL_STATUS
            failure_reasons.append(f"上牌时间过早: {register_month}")
            return
        if end and register_month > end:
            checks["register_date"] = FAIL_STATUS
            failure_reasons.append(f"上牌时间过晚: {register_month}")
            return
        checks["register_date"] = PASS_STATUS


def _normalize_string_list(
    value: Any,
    transform=None,
) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = re.split(r"[\n,]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = [value]

    normalized: list[str] = []
    seen = set()
    for item in raw_values:
        text = transform(item) if transform else _clean_text(item)
        if not text:
            continue
        dedupe_key = text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(text)
    return normalized


def _collect_vehicle_property_pairs(detail_payload: dict[str, Any]) -> list[tuple[str, str]]:
    item_do = ((detail_payload.get("data") or {}).get("itemDO") or {})
    pairs: list[tuple[str, str]] = []

    for label in item_do.get("cpvLabels") or []:
        if not isinstance(label, dict):
            continue
        name = _clean_text(label.get("propertyName"))
        value = _clean_text(label.get("valueName"))
        if name and value:
            pairs.append((name, value))

    for label in item_do.get("itemLabelExtList") or []:
        if not isinstance(label, dict):
            continue
        name = _clean_text(label.get("propertyText"))
        value = _clean_text(label.get("valueText") or label.get("text"))
        if name and value:
            pairs.append((name, value))

    return _dedupe_pairs(pairs)


def _coerce_int_or_none(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _collect_named_pairs(payload: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            label = _first_scalar_from_keys(node, GENERIC_LABEL_KEYS)
            value = _first_scalar_from_keys(node, GENERIC_VALUE_KEYS)
            if label and value and label != value:
                pairs.append((label, value))
            for child in node.values():
                walk(child)
            return
        if isinstance(node, list):
            for child in node:
                walk(child)

    walk(payload)
    return pairs


def _collect_scalar_pairs(payload: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                text = _as_scalar_text(value)
                if text is not None:
                    pairs.append((str(key), text))
                else:
                    walk(value)
            return
        if isinstance(node, list):
            for child in node:
                walk(child)

    walk(payload)
    return pairs


def _first_match(
    structured_pairs: list[tuple[str, str]],
    scalar_pairs: list[tuple[str, str]],
    label_hints: Iterable[str],
    key_hints: Iterable[str],
) -> Optional[str]:
    matches = _collect_matches(structured_pairs, scalar_pairs, label_hints, key_hints)
    return matches[0] if matches else None


def _collect_matches(
    structured_pairs: list[tuple[str, str]],
    scalar_pairs: list[tuple[str, str]],
    label_hints: Iterable[str],
    key_hints: Iterable[str],
) -> list[str]:
    matches: list[str] = []
    for label, value in structured_pairs:
        if _matches_hint(label, label_hints):
            matches.append(value)
    for key, value in scalar_pairs:
        if _matches_hint(key, key_hints):
            matches.append(value)
    return _dedupe_preserve_order(matches)


def _matches_hint(value: str, hints: Iterable[str]) -> bool:
    normalized = _normalize_hint_text(value)
    return any(_normalize_hint_text(hint) in normalized for hint in hints)


def _normalize_hint_text(value: Any) -> str:
    return re.sub(r"[\s_:/-]+", "", str(value or "")).lower()


def _first_scalar_from_keys(payload: dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        if key not in payload:
            continue
        text = _as_scalar_text(payload.get(key))
        if text:
            return text
    return None


def _as_scalar_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        return _clean_text(value)
    if isinstance(value, dict):
        for candidate_key in GENERIC_VALUE_KEYS:
            if candidate_key in value:
                text = _as_scalar_text(value.get(candidate_key))
                if text:
                    return text
    return None


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"none", "null", "undefined", "unknown", "未知"}:
        return None
    return text


def _parse_chinese_digit(text: str) -> Optional[int]:
    if text in CHINESE_DIGITS:
        return CHINESE_DIGITS[text]
    return None


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        dedupe_key = text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append(text)
    return result


def _dedupe_pairs(values: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen = set()
    for label, value in values:
        normalized_label = _clean_text(label)
        normalized_value = _clean_text(value)
        if not normalized_label or not normalized_value:
            continue
        dedupe_key = (normalized_label.lower(), normalized_value.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append((normalized_label, normalized_value))
    return result
