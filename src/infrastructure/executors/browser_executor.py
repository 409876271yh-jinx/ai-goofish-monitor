"""
受限浏览器动作执行器
只实现 best-effort 的联系卖家发送首句，不尝试绕过验证码或风控。
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


# TODO: 这些选择器基于当前闲鱼页面的常见文案做 best-effort 匹配；
# 若页面结构后续变化，需要在真实页面上重新校准。
CONTACT_BUTTON_SELECTORS = (
    "div[class*='left--']:has([data-spm='want'])",
    "div:has(> [data-spm='want'])",
    "[data-spm='want']",
    "button:has-text('聊一聊')",
    "a:has-text('聊一聊')",
    "button:has-text('去聊聊')",
    "a:has-text('去聊聊')",
    "button:has-text('发消息')",
    "a:has-text('发消息')",
    "button:has-text('私信')",
    "a:has-text('私信')",
    "button:has-text('联系卖家')",
    "button:has-text('我想要')",
    "a:has-text('联系卖家')",
    "a:has-text('我想要')",
    "text=聊一聊",
    "text=去聊聊",
    "text=发消息",
    "text=私信",
    "text=联系卖家",
    "text=我想要",
)
MESSAGE_INPUT_SELECTORS = (
    "textarea",
    "input[type='text']",
    "[contenteditable='true']",
)
CHAT_SURFACE_INPUT_SELECTORS = (
    "textarea[placeholder*='消息']",
    "textarea",
    "[contenteditable='true']",
    "input[placeholder*='消息']",
)
SEND_BUTTON_SELECTORS = (
    "button:has-text('发送')",
    "button:has-text('发 送')",
    "text=发送",
)
RISK_TEXT_MARKERS = (
    "验证码",
    "滑块",
    "安全验证",
    "风控",
    "登录",
    "短信验证",
    "非法访问",
    "请使用正常浏览器访问",
    "为了保障您的体验",
    "浏览器访问闲鱼",
)
EXTRA_CONFIRM_MARKERS = (
    "确认购买",
    "立即支付",
    "支付",
    "实名认证",
    "人脸验证",
)
LAUNCH_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
)


@dataclass(frozen=True)
class BrowserActionResult:
    success: bool
    status: str
    error: str = ""
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BrowserExecutor:
    """封装轻量级 Playwright 页面动作。"""

    async def send_message(
        self,
        item_url: str,
        message: str,
        login_state: Optional[str],
        *,
        timeout_ms: int = 15000,
    ) -> BrowserActionResult:
        if not item_url:
            return BrowserActionResult(
                success=False,
                status="invalid_input",
                error="missing_item_url",
                detail="未提供商品链接。",
            )
        if not message.strip():
            return BrowserActionResult(
                success=False,
                status="invalid_input",
                error="missing_message",
                detail="消息内容为空。",
            )
        if not login_state or not os.path.exists(login_state):
            return BrowserActionResult(
                success=False,
                status="invalid_input",
                error="missing_login_state",
                detail="登录状态文件不存在，无法安全执行页面动作。",
            )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                channel=self._resolve_browser_channel(),
                headless=self._resolve_headless_mode(),
                args=list(LAUNCH_ARGS),
            )
            context = await browser.new_context(
                storage_state=login_state,
                viewport={"width": 1440, "height": 1200},
            )
            page = await context.new_page()
            try:
                await page.goto(item_url, wait_until="domcontentloaded", timeout=timeout_ms)
                await page.wait_for_timeout(1500)
                risk = await self._detect_risk_or_login(page)
                if risk:
                    return risk

                chat_page_or_error = await self._open_chat_page(
                    page,
                    context,
                    timeout_ms=timeout_ms,
                )
                if isinstance(chat_page_or_error, BrowserActionResult):
                    return chat_page_or_error
                page = chat_page_or_error

                risk = await self._detect_risk_or_login(page)
                if risk:
                    return risk

                if await self._detect_extra_confirmation(page):
                    return BrowserActionResult(
                        success=False,
                        status="extra_confirmation_required",
                        error="extra_confirmation_required",
                        detail="页面要求额外交互确认，已停止自动发送。",
                        metadata={"item_url": item_url},
                    )

                input_locator = await self._wait_for_first_visible(
                    page,
                    MESSAGE_INPUT_SELECTORS,
                    timeout_ms=5000,
                )
                if input_locator is None:
                    return BrowserActionResult(
                        success=False,
                        status="selector_error",
                        error="message_input_not_found",
                        detail="未定位到消息输入框，已安全退出。",
                        metadata={
                            "item_url": item_url,
                            "page_url": page.url,
                            "body_excerpt": await self._extract_body_excerpt(page),
                        },
                    )

                await self._fill_message(page, input_locator, message)

                send_button = await self._wait_for_first_visible(
                    page,
                    SEND_BUTTON_SELECTORS,
                    timeout_ms=5000,
                )
                if send_button is None:
                    return BrowserActionResult(
                        success=False,
                        status="selector_error",
                        error="send_button_not_found",
                        detail="未定位到发送按钮，已安全退出。",
                        metadata={
                            "item_url": item_url,
                            "page_url": page.url,
                            "body_excerpt": await self._extract_body_excerpt(page),
                        },
                    )

                await send_button.click()
                await page.wait_for_timeout(1200)

                risk = await self._detect_risk_or_login(page)
                if risk:
                    return risk

                return BrowserActionResult(
                    success=True,
                    status="success",
                    detail="已完成一次受限首句发送尝试。",
                    metadata={"item_url": item_url},
                )
            except PlaywrightTimeoutError as exc:
                return BrowserActionResult(
                    success=False,
                    status="timeout",
                    error="playwright_timeout",
                    detail=str(exc),
                    metadata={"item_url": item_url},
                )
            except Exception as exc:
                return BrowserActionResult(
                    success=False,
                    status="unexpected_error",
                    error=type(exc).__name__,
                    detail=str(exc),
                    metadata={"item_url": item_url},
                )
            finally:
                await context.close()
                await browser.close()

    async def _wait_for_first_visible(
        self,
        page,
        selectors: tuple[str, ...],
        *,
        timeout_ms: int,
    ):
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
        return None

    async def _open_chat_page(
        self,
        page,
        context,
        *,
        timeout_ms: int,
    ):
        contact_button = await self._wait_for_first_visible(
            page,
            CONTACT_BUTTON_SELECTORS,
            timeout_ms=5000,
        )
        if contact_button is None:
            contact_button = await self._wait_for_contact_role_locator(page, timeout_ms=3000)

        if contact_button is None:
            return BrowserActionResult(
                success=False,
                status="selector_error",
                error="contact_button_not_found",
                detail="未定位到联系卖家入口，已安全退出。",
                metadata={
                    "item_url": page.url,
                    "body_excerpt": await self._extract_body_excerpt(page),
                },
            )

        click_error: Optional[Exception] = None
        click_attempts = await self._build_contact_click_attempts(contact_button)
        for click_kwargs in click_attempts:
            before_page_count = len(context.pages)
            try:
                await contact_button.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            try:
                await contact_button.click(**click_kwargs)
            except Exception as exc:
                click_error = exc
                continue

            target_page = await self._wait_for_chat_surface(
                page,
                context,
                before_page_count=before_page_count,
                timeout_ms=min(timeout_ms, 8000),
            )
            if target_page is not None:
                return target_page

            if self._is_purchase_page(page.url):
                return BrowserActionResult(
                    success=False,
                    status="extra_confirmation_required",
                    error="purchase_flow_detected",
                    detail="联系入口与购买按钮共用容器，当前页面进入了下单流程，已安全退出。",
                    metadata={
                        "page_url": page.url,
                        "body_excerpt": await self._extract_body_excerpt(page),
                    },
                )

        return BrowserActionResult(
            success=False,
            status="selector_error",
            error="chat_page_not_opened",
            detail="已定位到联系卖家入口，但未能打开聊天页，已安全退出。",
            metadata={
                "item_url": page.url,
                "page_url": page.url,
                "body_excerpt": await self._extract_body_excerpt(page),
                "last_click_error": str(click_error or ""),
            },
        )

    async def _build_contact_click_attempts(self, contact_button) -> tuple[dict[str, Any], ...]:
        try:
            button_text = " ".join((await contact_button.inner_text()).split())
        except Exception:
            button_text = ""

        if "立即购买" in button_text and ("聊一聊" in button_text or "联系卖家" in button_text):
            return (
                {"timeout": 5000, "force": True, "position": {"x": 80, "y": 20}},
                {"timeout": 5000, "force": True, "position": {"x": 60, "y": 18}},
                {"timeout": 5000, "force": True},
            )

        return (
            {"timeout": 5000},
            {"timeout": 5000, "force": True},
            {"timeout": 5000, "force": True, "position": {"x": 80, "y": 20}},
        )

    async def _wait_for_contact_role_locator(self, page, *, timeout_ms: int):
        patterns = (
            re.compile(r"联系卖家"),
            re.compile(r"我想要"),
            re.compile(r"聊一聊"),
            re.compile(r"去聊聊"),
            re.compile(r"发消息"),
            re.compile(r"私信"),
        )
        for pattern in patterns:
            for locator in (
                page.get_by_role("button", name=pattern).first,
                page.get_by_role("link", name=pattern).first,
                page.get_by_text(pattern, exact=False).first,
            ):
                try:
                    await locator.wait_for(state="visible", timeout=timeout_ms)
                    return locator
                except Exception:
                    continue
        return None

    async def _wait_for_chat_surface(
        self,
        page,
        context,
        *,
        before_page_count: int,
        timeout_ms: int,
    ):
        deadline = time.monotonic() + max(timeout_ms, 1000) / 1000.0
        while time.monotonic() < deadline:
            if len(context.pages) > before_page_count:
                target_page = context.pages[-1]
                try:
                    await target_page.wait_for_load_state("domcontentloaded", timeout=3000)
                except Exception:
                    pass
                return target_page

            if self._is_chat_page(page.url):
                return page

            input_locator = await self._wait_for_first_visible(
                page,
                CHAT_SURFACE_INPUT_SELECTORS,
                timeout_ms=500,
            )
            if input_locator is not None:
                return page

            await page.wait_for_timeout(250)
        return None

    async def _fill_message(self, page, locator, message: str) -> None:
        try:
            await locator.fill(message)
            return
        except Exception:
            pass

        try:
            await locator.click()
            await page.keyboard.insert_text(message)
            return
        except Exception as exc:
            raise RuntimeError(f"无法写入消息输入框: {exc}") from exc

    async def _detect_risk_or_login(self, page) -> Optional[BrowserActionResult]:
        lowered_url = (page.url or "").lower()
        if "passport.goofish.com" in lowered_url or "mini_login" in lowered_url:
            return BrowserActionResult(
                success=False,
                status="login_required",
                error="login_required",
                detail="页面跳转到了登录流程，已停止自动动作。",
                metadata={"url": page.url},
            )

        try:
            body_text = await page.locator("body").inner_text(timeout=2000)
        except Exception:
            body_text = ""

        for marker in RISK_TEXT_MARKERS:
            if marker in body_text:
                return BrowserActionResult(
                    success=False,
                    status="risk_control",
                    error="risk_control_detected",
                    detail=f"检测到风险控制信号: {marker}",
                    metadata={"url": page.url},
                )
        return None

    async def _detect_extra_confirmation(self, page) -> bool:
        try:
            body_text = await page.locator("body").inner_text(timeout=2000)
        except Exception:
            return False
        return any(marker in body_text for marker in EXTRA_CONFIRM_MARKERS)

    async def _extract_body_excerpt(self, page, limit: int = 600) -> str:
        try:
            body_text = await page.locator("body").inner_text(timeout=2000)
        except Exception:
            return ""
        normalized = " ".join(str(body_text or "").split())
        return normalized[:limit]

    def _is_chat_page(self, url: str) -> bool:
        lowered_url = str(url or "").lower()
        return "/im?" in lowered_url or lowered_url.endswith("/im")

    def _is_purchase_page(self, url: str) -> bool:
        lowered_url = str(url or "").lower()
        return "/create-order" in lowered_url or "confirm-buy" in lowered_url

    def _resolve_browser_channel(self) -> str:
        running_in_docker = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"
        login_is_edge = os.getenv("LOGIN_IS_EDGE", "false").lower() == "true"
        if running_in_docker:
            return "chromium"
        return "msedge" if login_is_edge else "chrome"

    def _resolve_headless_mode(self) -> bool:
        configured = os.getenv("ACTION_BROWSER_HEADLESS")
        if configured is not None:
            return configured.lower() == "true"
        return os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"
