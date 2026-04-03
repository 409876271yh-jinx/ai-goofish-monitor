"""
商品分析分发器
将卖家资料采集、图片下载、AI 分析和结果保存移出主抓取链路。
"""
import asyncio
import copy
import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from src.keyword_rule_engine import build_search_text, evaluate_keyword_rules
from src.services.action_service import ActionService
from src.services.structured_filter_service import (
    STRUCTURED_FILTER_ANALYSIS_SOURCE,
    StructuredFilterService,
)


SellerLoader = Callable[[str], Awaitable[dict]]
ImageDownloader = Callable[[str, list[str], str], Awaitable[list[str]]]
AIAnalyzer = Callable[[dict, list[str], str], Awaitable[Optional[dict]]]
Notifier = Callable[[dict, str], Awaitable[None]]
Saver = Callable[[dict, str], Awaitable[bool]]


@dataclass(frozen=True)
class ItemAnalysisJob:
    keyword: str
    task_name: str
    decision_mode: str
    analyze_images: bool
    prompt_text: str
    keyword_rules: tuple[str, ...]
    final_record: dict
    seller_id: Optional[str]
    zhima_credit_text: Optional[str]
    registration_duration_text: str
    task_id: Optional[int] = None
    login_state_path: Optional[str] = None
    task_max_price: Optional[str] = None
    action_settings: Optional[dict] = None
    enable_structured_prefilter: bool = False
    vehicle_filter: Optional[dict] = None
    detail_payload: Optional[dict] = None


class ItemAnalysisDispatcher:
    """用受控并发处理商品分析和落盘。"""

    def __init__(
        self,
        *,
        concurrency: int,
        skip_ai_analysis: bool,
        seller_loader: SellerLoader,
        image_downloader: ImageDownloader,
        ai_analyzer: AIAnalyzer,
        notifier: Notifier,
        saver: Saver,
        action_service: Optional[ActionService] = None,
        structured_filter_service: Optional[StructuredFilterService] = None,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._skip_ai_analysis = skip_ai_analysis
        self._seller_loader = seller_loader
        self._image_downloader = image_downloader
        self._ai_analyzer = ai_analyzer
        self._notifier = notifier
        self._saver = saver
        self._action_service = action_service
        self._structured_filter_service = structured_filter_service or StructuredFilterService()
        self._tasks: set[asyncio.Task] = set()
        self.completed_count = 0

    def submit(self, job: ItemAnalysisJob) -> None:
        task = asyncio.create_task(self._process_with_limit(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def join(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))

    async def _process_with_limit(self, job: ItemAnalysisJob) -> None:
        async with self._semaphore:
            await self._process_job(job)

    async def _process_job(self, job: ItemAnalysisJob) -> None:
        record = copy.deepcopy(job.final_record)
        item_data = record.get("商品信息", {}) or {}
        record["卖家信息"] = await self._load_seller_info(job)
        record["ai_analysis"] = await self._build_analysis_result(job, record)
        if await self._saver(record, job.keyword):
            self.completed_count += 1
        await self._handle_recommended_item(job, record, item_data)

    async def _load_seller_info(self, job: ItemAnalysisJob) -> dict:
        seller_info = {}
        if job.seller_id:
            try:
                seller_info = await self._seller_loader(job.seller_id)
            except Exception as exc:
                print(f"   [卖家] 采集卖家 {job.seller_id} 信息失败: {exc}")
        merged = copy.deepcopy(seller_info or {})
        merged["卖家芝麻信用"] = job.zhima_credit_text
        merged["卖家注册时长"] = job.registration_duration_text
        return merged

    async def _build_analysis_result(self, job: ItemAnalysisJob, record: dict) -> dict:
        if job.decision_mode == "keyword":
            return self._build_keyword_result(job, record)
        structured_filter_result = self._run_structured_prefilter(job, record)
        if structured_filter_result is not None:
            self._attach_structured_filter_result(record, structured_filter_result)
            if not structured_filter_result.get("passed", True):
                return self._build_structured_filter_reject_result(structured_filter_result)
        if self._skip_ai_analysis:
            return self._build_skip_ai_result()
        return await self._run_ai_analysis(job, record)

    def _build_keyword_result(self, job: ItemAnalysisJob, record: dict) -> dict:
        search_text = build_search_text(record)
        return evaluate_keyword_rules(list(job.keyword_rules), search_text)

    def _build_skip_ai_result(self) -> dict:
        return {
            "analysis_source": "ai",
            "is_recommended": True,
            "reason": "商品已跳过AI分析，直接通知",
            "keyword_hit_count": 0,
        }

    def _build_ai_error_result(self, reason: str, *, error: str = "") -> dict:
        payload = {
            "analysis_source": "ai",
            "is_recommended": False,
            "reason": reason,
            "keyword_hit_count": 0,
        }
        if error:
            payload["error"] = error
        return payload

    def _run_structured_prefilter(
        self,
        job: ItemAnalysisJob,
        record: dict,
    ) -> Optional[dict]:
        if not job.enable_structured_prefilter:
            return None
        return self._structured_filter_service.evaluate_vehicle_filter(
            record=record,
            detail_payload=job.detail_payload,
            vehicle_filter=job.vehicle_filter,
        )

    def _attach_structured_filter_result(self, record: dict, result: dict) -> None:
        record["structured_filter_passed"] = bool(result.get("passed", False))
        record["structured_filter_reason"] = str(result.get("reason") or "")
        record["structured_filter_checks"] = dict(result.get("checks") or {})
        record["normalized_fields"] = dict(result.get("normalized_fields") or {})

    def _build_structured_filter_reject_result(self, result: dict) -> dict:
        return {
            "analysis_source": STRUCTURED_FILTER_ANALYSIS_SOURCE,
            "is_recommended": False,
            "reason": str(result.get("reason") or "结构化字段预筛选未通过"),
            "keyword_hit_count": 0,
        }

    async def _run_ai_analysis(self, job: ItemAnalysisJob, record: dict) -> dict:
        image_paths: list[str] = []
        try:
            image_paths = await self._download_images(job, record)
            if not job.prompt_text:
                return self._build_ai_error_result("任务未配置AI prompt，跳过分析。")
            ai_result = await self._ai_analyzer(record, image_paths, job.prompt_text)
            if not ai_result:
                return self._build_ai_error_result(
                    "AI analysis returned None after retries.",
                    error="AI analysis returned None after retries.",
                )
            ai_result.setdefault("analysis_source", "ai")
            ai_result.setdefault("keyword_hit_count", 0)
            return ai_result
        except Exception as exc:
            return self._build_ai_error_result(
                f"AI分析异常: {exc}",
                error=str(exc),
            )
        finally:
            self._cleanup_images(image_paths)

    async def _download_images(self, job: ItemAnalysisJob, record: dict) -> list[str]:
        if not job.analyze_images:
            return []
        item_data = record.get("商品信息", {}) or {}
        image_urls = item_data.get("商品图片列表", [])
        if not image_urls:
            return []
        return await self._image_downloader(
            item_data["商品ID"],
            image_urls,
            job.task_name,
        )

    def _cleanup_images(self, image_paths: list[str]) -> None:
        for img_path in image_paths:
            try:
                if os.path.exists(img_path):
                    os.remove(img_path)
            except Exception as exc:
                print(f"   [图片] 删除图片文件时出错: {exc}")

    async def _notify_if_recommended(self, item_data: dict, analysis_result: dict) -> None:
        if not analysis_result.get("is_recommended"):
            return
        try:
            await self._notifier(item_data, analysis_result.get("reason", "无"))
        except Exception as exc:
            print(f"   [通知] 发送推荐通知失败: {exc}")

    async def _handle_recommended_item(
        self,
        job: ItemAnalysisJob,
        record: dict,
        item_data: dict,
    ) -> None:
        analysis_result = record.get("ai_analysis", {}) or {}
        if not analysis_result.get("is_recommended"):
            return

        action_enabled = bool((job.action_settings or {}).get("enabled"))
        if self._action_service is not None and action_enabled:
            try:
                await self._action_service.handle_recommended_item(
                    task_id=job.task_id,
                    task_name=job.task_name,
                    record=record,
                    analysis_result=analysis_result,
                    login_state_path=job.login_state_path,
                    seller_id=job.seller_id,
                    task_max_price=job.task_max_price,
                    action_settings=job.action_settings,
                )
            except Exception as exc:
                print(f"   [ActionEngine] 动作执行失败，已忽略并继续主流程: {exc}")
            return

        await self._notify_if_recommended(item_data, analysis_result)
