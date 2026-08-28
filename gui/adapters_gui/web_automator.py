"""Web 自动化执行器：DOM 级驱动真实浏览器（Playwright/Chromium）。

用于 Web/浏览器类软件（software_id ∈ {chrome, edge, msedge, firefox, web, browser}）的 GUI 意图。
与桌面 UIA 执行器（executor.AutomationExecutor）并列：Chromium/Electron 应用对 UIA 遍历
极敏感（ndll 崩溃且无法被捕获），故 web 任务走独立 DOM 通道，不复用桌面坐标/转移记忆。

动作契约（steps: list[dict]，必填 action）：
- navigate : target/value=URL（自动补 https://；支持 file:///data:）
- click    : target=可见文字(交互元素内模糊匹配) 或 selector=css/xpath，点击
- fill     : selector 或 target(placeholder/label 模糊) + value，填入文本
- type     : value，向当前焦点输入文本
- press    : value，按键（Enter/Escape...）
- read     : target=区域文字(可选)，抓取页面文本
- verify   : expect=[子串...]，校验页面是否包含，决定该步成败
- screenshot: target=保存路径，存图

返回 (ok, detail) 与桌面执行器一致，供 automation_orchestrator 统一闭环。
Playwright 仅在 ensure_browser 时惰性导入——未安装不影响桌面自动化模块的导入。
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

# web 类 software_id：编排器据此把意图路由到本执行器而非桌面 UIA 执行器。
# 含 msedge（WindowsAgentArena 用 msedge 而非 edge 作 software_id）。
WEB_SOFTWARE_IDS = {"chrome", "edge", "msedge", "firefox", "web", "browser"}


class WebAutomationExecutor:
    """真实浏览器 DOM 级执行器（Playwright Chromium）。"""

    def __init__(self, software_id: str = "chrome", headless: bool = True):
        self.software_id = software_id or "chrome"
        self._headless = headless
        self._playwright = None
        self._browser = None
        self._page = None

    # ── 浏览器生命周期 ──
    async def ensure_browser(self) -> None:
        """惰性启动 Chromium；Playwright 未装时抛出明确错误（不静默吞掉）。"""
        if self._browser is not None:
            return
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._page = await self._browser.new_page()
        self._page.set_default_timeout(15000)

    async def close(self) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:
            pass

    # ── 元素定位 ──
    _INTERACTIVE = "button, a, input[type=button], input[type=submit], [role=button], [role=link]"

    def _locator(self, step: dict):
        """按 selector 或文字返回定位器；文字匹配限定在交互元素内，避免命中正文。"""
        selector = step.get("selector")
        if selector:
            if selector.startswith("xpath="):
                return self._page.locator("xpath=" + selector[len("xpath="):])
            if selector.startswith("css="):
                return self._page.locator(selector[len("css="):])
            return self._page.locator(selector)
        target = step.get("target") or step.get("name") or ""
        return self._page.locator(self._INTERACTIVE).filter(has_text=target).first

    # ── 主执行 ──
    async def run(self, steps: list[dict]) -> tuple[bool, str]:
        if not isinstance(steps, list) or not steps:
            return False, "规划为空：没有可执行的步骤。"
        try:
            await self.ensure_browser()
        except Exception as exc:
            return False, f"浏览器启动失败: {exc}"
        details: list[str] = []
        ok = True
        for idx, step in enumerate(steps, 1):
            action = (step.get("action") or "").lower()
            detail = await self._act(action, step)
            details.append(f"第{idx}步 {action}: {detail}")
            if detail.startswith("失败"):
                ok = False
        verdict = "状态: 完成" if ok else "状态: 部分失败"
        return ok, verdict + "\n" + "\n".join(details)

    async def _act(self, action: str, step: dict) -> str:
        try:
            if action == "navigate":
                url = step.get("target") or step.get("value") or ""
                if not url:
                    return "失败: navigate 缺 URL"
                # 浏览器内部 scheme（edge://、chrome://、about:）已是合法地址，
                # 不可误加 https:// 前缀（否则退化成 https://edge//... 触发 DNS 失败）。
                if not url.startswith(("http://", "https://", "file://",
                                       "data:", "edge://", "chrome://", "about:")):
                    url = "https://" + url
                await self._page.goto(url, wait_until="load")
                return f"已打开 {url}"
            if action == "wait":
                # 与桌面执行器对齐：wait 用 seconds（兼容 timeout 别名），仅页面内等待不阻塞
                secs = float(step.get("seconds") or step.get("timeout") or 1.0)
                await self._page.wait_for_timeout(int(secs * 1000))
                return f"等待 {secs}s"
            if action == "click":
                loc = self._locator(step)
                await loc.click()
                await self._page.wait_for_timeout(120)
                return "已点击"
            if action == "fill":
                value = step.get("value", "")
                selector = step.get("selector")
                if selector:
                    loc = self._page.locator(selector)
                else:
                    target = step.get("target") or ""
                    loc = self._page.get_by_placeholder(target).first
                await loc.fill(value)
                await self._page.wait_for_timeout(80)
                return f"已填入 {value!r}"
            if action == "type":
                await self._page.keyboard.type(step.get("value", ""))
                await self._page.wait_for_timeout(80)
                return "已输入"
            if action == "press":
                await self._page.keyboard.press(step.get("value", "Enter"))
                await self._page.wait_for_timeout(80)
                return f"已按键 {step.get('value')}"
            if action == "read":
                text = await self._page.inner_text("body")
                target = step.get("target")
                if target:
                    idx = text.find(target)
                    snippet = text[idx: idx + 240] if idx >= 0 else text[:240]
                    return f"读取到: {snippet}"
                return f"页面文本(前300): {text[:300]}"
            if action == "verify":
                expect = step.get("expect") or []
                body = await self._page.inner_text("body")
                missing = [e for e in expect if e not in body]
                return "校验通过" if not missing else f"失败: 缺少 {missing}"
            if action == "screenshot":
                path = step.get("target") or step.get("value") or "web_shot.png"
                await self._page.screenshot(path=path)
                return f"已截图 {path}"
            return f"失败: 不支持的 action={action!r}"
        except Exception as exc:
            return f"失败: {type(exc).__name__}: {exc}"
