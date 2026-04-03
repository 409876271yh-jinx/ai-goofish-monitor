from src.services.structured_filter_service import (
    StructuredFilterService,
    normalize_series,
    normalize_variant,
    parse_location,
    parse_mileage_km,
    parse_register_month,
    parse_transfer_count,
)


def _build_detail_payload(
    *,
    series: str = "Model Y",
    variant: str = "2024款 后轮驱动版 纯电动",
    mileage: str = "1.8万公里",
    transfer: str = "未过户",
    location: str = "四川成都",
    register_month: str = "2024年11月",
):
    return {
        "data": {
            "itemDO": {
                "structuredAttributes": [
                    {"name": "车系", "value": series},
                    {"name": "车型", "value": variant},
                    {"name": "表显里程", "value": mileage},
                    {"name": "过户次数", "value": transfer},
                    {"name": "车源地", "value": location},
                    {"name": "上牌时间", "value": register_month},
                ]
            }
        }
    }


def _build_vehicle_filter():
    return {
        "series": ["Model Y"],
        "variant_keywords": ["2024款", "后轮驱动", "纯电动"],
        "mileage_km_min": 10000,
        "mileage_km_max": 35000,
        "transfer_count": 0,
        "locations": ["四川", "重庆"],
        "register_month_start": "2024-09",
        "register_month_end": "2025-03",
    }


def test_structured_filter_service_passes_valid_model_y_sample():
    service = StructuredFilterService()
    result = service.evaluate_vehicle_filter(
        record={"商品信息": {"发货地区": "四川成都"}},
        detail_payload=_build_detail_payload(),
        vehicle_filter=_build_vehicle_filter(),
    )

    assert result["passed"] is True
    assert result["reason"] == "结构化字段全部满足"
    assert result["checks"]["series"] == "pass"
    assert result["checks"]["variant"] == "pass"
    assert result["checks"]["mileage"] == "pass"
    assert result["checks"]["transfer_count"] == "pass"
    assert result["checks"]["location"] == "pass"
    assert result["checks"]["register_date"] == "pass"
    assert result["normalized_fields"]["series"] == "Model Y"
    assert result["normalized_fields"]["mileage_km"] == 18000
    assert result["normalized_fields"]["transfer_count"] == 0
    assert result["normalized_fields"]["location"] == "四川"
    assert result["normalized_fields"]["register_month"] == "2024-11"


def test_structured_filter_service_blocks_non_model_y():
    service = StructuredFilterService()
    result = service.evaluate_vehicle_filter(
        record={"商品信息": {"发货地区": "四川成都"}},
        detail_payload=_build_detail_payload(series="Model 3"),
        vehicle_filter=_build_vehicle_filter(),
    )

    assert result["passed"] is False
    assert result["checks"]["series"] == "fail"
    assert "车系不匹配" in result["reason"]


def test_structured_filter_service_blocks_when_mileage_exceeds_limit():
    service = StructuredFilterService()
    result = service.evaluate_vehicle_filter(
        record={"商品信息": {"发货地区": "四川成都"}},
        detail_payload=_build_detail_payload(mileage="4.2万公里"),
        vehicle_filter=_build_vehicle_filter(),
    )

    assert result["passed"] is False
    assert result["checks"]["mileage"] == "fail"
    assert "里程过高" in result["reason"]


def test_structured_filter_service_blocks_when_transfer_count_differs():
    service = StructuredFilterService()
    result = service.evaluate_vehicle_filter(
        record={"商品信息": {"发货地区": "四川成都"}},
        detail_payload=_build_detail_payload(transfer="1次过户"),
        vehicle_filter=_build_vehicle_filter(),
    )

    assert result["passed"] is False
    assert result["checks"]["transfer_count"] == "fail"
    assert "过户次数不匹配" in result["reason"]


def test_structured_filter_service_blocks_when_location_differs():
    service = StructuredFilterService()
    result = service.evaluate_vehicle_filter(
        record={"商品信息": {"发货地区": "湖南长沙"}},
        detail_payload=_build_detail_payload(location="湖南长沙"),
        vehicle_filter=_build_vehicle_filter(),
    )

    assert result["passed"] is False
    assert result["checks"]["location"] == "fail"
    assert "地区不匹配" in result["reason"]


def test_structured_filter_service_blocks_when_register_month_out_of_range():
    service = StructuredFilterService()
    result = service.evaluate_vehicle_filter(
        record={"商品信息": {"发货地区": "四川成都"}},
        detail_payload=_build_detail_payload(register_month="2024年05月"),
        vehicle_filter=_build_vehicle_filter(),
    )

    assert result["passed"] is False
    assert result["checks"]["register_date"] == "fail"
    assert "上牌时间过早" in result["reason"]


def test_structured_filter_service_parses_common_text_formats():
    assert normalize_series("特斯拉 Model Y 后轮驱动版") == "Model Y"
    assert normalize_variant(" 2024款   后轮驱动版 纯电动 ") == "2024款 后轮驱动版 纯电动"
    assert parse_mileage_km("1.8万公里") == 18000
    assert parse_mileage_km("18000公里") == 18000
    assert parse_mileage_km("3万-4万公里") == 40000
    assert parse_transfer_count("未过户") == 0
    assert parse_transfer_count("0次过户") == 0
    assert parse_register_month("2024年11月") == "2024-11"
    assert parse_register_month("2024年 04月") == "2024-04"
    assert parse_location("四川成都") == "四川"


def test_structured_filter_service_prefers_platform_vehicle_property_pairs():
    service = StructuredFilterService()
    detail_payload = {
        "data": {
            "itemDO": {
                "cpvLabels": [
                    {"propertyName": "品牌", "valueName": "Tesla/特斯拉"},
                    {"propertyName": "车系", "valueName": "Model Y"},
                    {"propertyName": "车型", "valueName": "2024款 特斯拉MODEL Y后轮驱动版纯电动"},
                    {"propertyName": "里程", "valueName": "3万-4万公里"},
                    {"propertyName": "过户次数", "valueName": "1次"},
                    {"propertyName": "车源地", "valueName": "广东 深圳"},
                    {"propertyName": "上牌年月", "valueName": "2024年 04月"},
                ],
                "detailSpiVersion": "2",
            }
        }
    }

    result = service.evaluate_vehicle_filter(
        record={"商品信息": {"发货地区": "广东深圳"}},
        detail_payload=detail_payload,
        vehicle_filter={
            "series": ["Model Y"],
            "variant_keywords": ["2024款", "后轮驱动", "纯电动"],
            "transfer_count": 1,
            "locations": ["广东"],
            "register_month_start": "2024-01",
            "register_month_end": "2024-12",
        },
    )

    assert result["normalized_fields"]["series"] == "Model Y"
    assert result["normalized_fields"]["variant_text"] == "Model Y 2024款 特斯拉MODEL Y后轮驱动版纯电动"
    assert result["normalized_fields"]["mileage_km"] == 40000
    assert result["normalized_fields"]["transfer_count"] == 1
    assert result["normalized_fields"]["location"] == "广东"
    assert result["normalized_fields"]["register_month"] == "2024-04"
    assert result["checks"]["series"] == "pass"
    assert result["checks"]["variant"] == "pass"
