import asyncio

from src.services.item_analysis_dispatcher import (
    ItemAnalysisDispatcher,
    ItemAnalysisJob,
)


def test_item_analysis_dispatcher_uses_bounded_concurrency():
    active_ai_calls = 0
    max_active_ai_calls = 0
    saved_records = []
    notifications = []

    async def seller_loader(user_id: str):
        await asyncio.sleep(0.005)
        return {"卖家ID": user_id}

    async def image_downloader(product_id: str, image_urls: list[str], task_name: str):
        return []

    async def ai_analyzer(record: dict, image_paths: list[str], prompt_text: str):
        nonlocal active_ai_calls, max_active_ai_calls
        active_ai_calls += 1
        max_active_ai_calls = max(max_active_ai_calls, active_ai_calls)
        await asyncio.sleep(0.03)
        active_ai_calls -= 1
        return {
            "analysis_source": "ai",
            "is_recommended": True,
            "reason": f"推荐 {record['商品信息']['商品ID']}",
            "keyword_hit_count": 0,
        }

    async def notifier(item_data: dict, reason: str):
        notifications.append((item_data["商品ID"], reason))

    async def saver(record: dict, keyword: str):
        saved_records.append((keyword, record))
        return True

    async def run():
        dispatcher = ItemAnalysisDispatcher(
            concurrency=2,
            skip_ai_analysis=False,
            seller_loader=seller_loader,
            image_downloader=image_downloader,
            ai_analyzer=ai_analyzer,
            notifier=notifier,
            saver=saver,
        )
        for index in range(3):
            dispatcher.submit(
                ItemAnalysisJob(
                    keyword="demo",
                    task_name="Demo",
                    decision_mode="ai",
                    analyze_images=False,
                    prompt_text="prompt",
                    keyword_rules=(),
                    final_record={
                        "商品信息": {"商品ID": str(index), "商品图片列表": []},
                        "卖家信息": {},
                    },
                    seller_id=f"seller-{index}",
                    zhima_credit_text="优秀",
                    registration_duration_text="来闲鱼1年",
                )
            )
        await dispatcher.join()
        return dispatcher

    dispatcher = asyncio.run(run())
    assert dispatcher.completed_count == 3
    assert len(saved_records) == 3
    assert len(notifications) == 3
    assert max_active_ai_calls == 2
    assert saved_records[0][1]["卖家信息"]["卖家ID"].startswith("seller-")


def test_item_analysis_dispatcher_supports_keyword_mode_without_ai():
    saved_records = []

    async def seller_loader(user_id: str):
        return {"卖家标签": "个人闲置"}

    async def image_downloader(product_id: str, image_urls: list[str], task_name: str):
        raise AssertionError("关键词模式不应下载图片")

    async def ai_analyzer(record: dict, image_paths: list[str], prompt_text: str):
        raise AssertionError("关键词模式不应调用 AI")

    async def notifier(item_data: dict, reason: str):
        return None

    async def saver(record: dict, keyword: str):
        saved_records.append(record)
        return True

    async def run():
        dispatcher = ItemAnalysisDispatcher(
            concurrency=1,
            skip_ai_analysis=False,
            seller_loader=seller_loader,
            image_downloader=image_downloader,
            ai_analyzer=ai_analyzer,
            notifier=notifier,
            saver=saver,
        )
        dispatcher.submit(
            ItemAnalysisJob(
                keyword="demo",
                task_name="Demo",
                decision_mode="keyword",
                analyze_images=False,
                prompt_text="",
                keyword_rules=("个人闲置",),
                final_record={
                    "商品信息": {"商品ID": "1", "商品标题": "演示商品"},
                    "卖家信息": {},
                },
                seller_id="seller-1",
                zhima_credit_text="优秀",
                registration_duration_text="来闲鱼1年",
            )
        )
        await dispatcher.join()

    asyncio.run(run())
    assert saved_records[0]["ai_analysis"]["analysis_source"] == "keyword"
    assert saved_records[0]["ai_analysis"]["is_recommended"] is True


def test_item_analysis_dispatcher_skips_ai_when_structured_prefilter_fails():
    saved_records = []
    notifications = []

    async def seller_loader(user_id: str):
        return {"卖家ID": user_id}

    async def image_downloader(product_id: str, image_urls: list[str], task_name: str):
        return []

    async def ai_analyzer(record: dict, image_paths: list[str], prompt_text: str):
        raise AssertionError("结构化预筛选未通过时不应调用 AI")

    async def notifier(item_data: dict, reason: str):
        notifications.append((item_data.get("商品ID"), reason))

    async def saver(record: dict, keyword: str):
        saved_records.append(record)
        return True

    detail_payload = {
        "data": {
            "itemDO": {
                "structuredAttributes": [
                    {"name": "车系", "value": "Model 3"},
                    {"name": "车型", "value": "2024款 后轮驱动版 纯电动"},
                    {"name": "表显里程", "value": "1.8万公里"},
                    {"name": "过户次数", "value": "未过户"},
                    {"name": "车源地", "value": "四川成都"},
                    {"name": "上牌时间", "value": "2024年11月"},
                ]
            }
        }
    }

    async def run():
        dispatcher = ItemAnalysisDispatcher(
            concurrency=1,
            skip_ai_analysis=False,
            seller_loader=seller_loader,
            image_downloader=image_downloader,
            ai_analyzer=ai_analyzer,
            notifier=notifier,
            saver=saver,
        )
        dispatcher.submit(
            ItemAnalysisJob(
                keyword="model y",
                task_name="Vehicle Demo",
                decision_mode="ai",
                analyze_images=False,
                prompt_text="prompt",
                keyword_rules=(),
                final_record={
                    "商品信息": {
                        "商品ID": "vehicle-1",
                        "商品标题": "特斯拉二手车",
                        "发货地区": "四川成都",
                    },
                    "卖家信息": {},
                },
                seller_id="seller-vehicle-1",
                zhima_credit_text="优秀",
                registration_duration_text="来闲鱼2年",
                enable_structured_prefilter=True,
                vehicle_filter={
                    "series": ["Model Y"],
                    "mileage_km_min": 10000,
                    "mileage_km_max": 35000,
                },
                detail_payload=detail_payload,
            )
        )
        await dispatcher.join()

    asyncio.run(run())

    assert len(saved_records) == 1
    assert saved_records[0]["structured_filter_passed"] is False
    assert saved_records[0]["structured_filter_checks"]["series"] == "fail"
    assert saved_records[0]["ai_analysis"]["analysis_source"] == "structured_filter"
    assert saved_records[0]["ai_analysis"]["is_recommended"] is False
    assert notifications == []
