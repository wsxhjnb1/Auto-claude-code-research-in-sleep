# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived for ARIS browser-backed Gemini illustration runtime.

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import IllustrationConfig

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - exercised via status() in envs without playwright
    sync_playwright = None
    PlaywrightTimeoutError = RuntimeError
    PLAYWRIGHT_IMPORT_ERROR = exc
else:
    PLAYWRIGHT_IMPORT_ERROR = None


PROMPT_BOX_SELECTORS = [
    'textarea[aria-label*="prompt" i]',
    'textarea[placeholder*="prompt" i]',
    'textarea',
    'div[contenteditable="true"][role="textbox"]',
    'div[contenteditable="true"]',
]

LOGIN_HINT_SELECTORS = [
    'input[type="email"]',
    'input[type="password"]',
    'form[action*="accounts"]',
]

DOWNLOAD_BUTTON_REGEX = re.compile(
    r"(download|save image|save|下载|保存)",
    re.IGNORECASE,
)

SUBMIT_BUTTON_REGEX = re.compile(
    r"(send|submit|run|generate|create|生成|发送|运行)",
    re.IGNORECASE,
)

SIGN_IN_REGEX = re.compile(r"(sign in|登录|登入)", re.IGNORECASE)

STYLE_RULES = [
    "white or near-white background",
    "no figure title inside the image",
    "explicit module labels and arrow directions",
    "publication-quality academic diagram style",
    "print-friendly palette and grayscale readability",
    "clean spacing, clear hierarchy, minimal decorative clutter",
]


@dataclass
class BrowserRunResult:
    status: str
    message: str
    output_path: str | None = None
    debug_bundle_path: str | None = None
    artifact_method: str | None = None
    selector_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "output_path": self.output_path,
            "debug_bundle_path": self.debug_bundle_path,
            "artifact_method": self.artifact_method,
            "selector_report": self.selector_report,
        }


class GeminiBrowserBackend:
    """Browser-backed renderer that reuses a dedicated Gemini web profile."""

    def __init__(self, config: IllustrationConfig) -> None:
        self.config = config
        style_path = (
            Path(__file__).resolve().parent
            / "style_guides"
            / "neurips2025_diagram_style_guide.md"
        )
        self.style_guide = style_path.read_text(encoding="utf-8")

    def status(self) -> BrowserRunResult:
        if sync_playwright is None:
            return BrowserRunResult(
                status="playwright_missing",
                message=(
                    "Playwright is not installed. Run "
                    "`python3 tools/ensure_paper_runtime.py --phase illustration` "
                    "or inspect refine-logs/PAPER_RUNTIME_STATE.json."
                ),
            )

        profile_exists = self.config.browser_profile_dir.exists()
        self.config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        console_messages: list[dict[str, Any]] = []
        selector_report: dict[str, Any] = {
            "profile_exists": profile_exists,
            "profile_dir": str(self.config.browser_profile_dir),
        }
        try:
            with sync_playwright() as playwright:
                context = self._launch_context(playwright, headless=self.config.browser_headless)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    self._attach_console_logging(page, console_messages)
                    self._navigate_to_app(page)
                    state, selector_report = self._detect_state(page)
                    if state == "ready":
                        return BrowserRunResult(
                            status="ready",
                            message=(
                                f"Gemini browser backend is ready. "
                                f"Using profile {self.config.browser_profile_dir}."
                            ),
                            selector_report=selector_report,
                        )
                    return BrowserRunResult(
                        status=state,
                        message=(
                            "Gemini browser profile exists but login is required."
                            if state == "needs_login"
                            else "Gemini browser page loaded but prompt box could not be confirmed."
                        ),
                        selector_report=selector_report,
                    )
                finally:
                    context.close()
        except Exception as exc:
            debug_bundle = self._write_debug_bundle(
                console_messages=console_messages,
                selector_report=selector_report,
                label="status-failure",
                page=None,
            )
            return BrowserRunResult(
                status="backend_blocker",
                message=f"Gemini browser status check failed: {exc}",
                debug_bundle_path=str(debug_bundle),
                selector_report=selector_report,
            )

    def login(self, *, timeout_sec: int | None = None) -> BrowserRunResult:
        if sync_playwright is None:
            return BrowserRunResult(
                status="playwright_missing",
                message=(
                    "Playwright is not installed. Run "
                    "`python3 tools/ensure_paper_runtime.py --phase illustration` "
                    "or inspect refine-logs/PAPER_RUNTIME_STATE.json."
                ),
            )

        self.config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        timeout = int(timeout_sec or self.config.browser_timeout_sec)
        console_messages: list[dict[str, Any]] = []
        selector_report: dict[str, Any] = {}
        try:
            with sync_playwright() as playwright:
                context = self._launch_context(playwright, headless=False)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    self._attach_console_logging(page, console_messages)
                    self._navigate_to_app(page)
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        state, selector_report = self._detect_state(page)
                        if state == "ready":
                            return BrowserRunResult(
                                status="ready",
                                message=(
                                    "Gemini login detected and persisted to the dedicated "
                                    f"profile at {self.config.browser_profile_dir}."
                                ),
                                selector_report=selector_report,
                            )
                        page.wait_for_timeout(1500)
                    debug_bundle = self._write_debug_bundle(
                        console_messages=console_messages,
                        selector_report=selector_report,
                        label="login-timeout",
                        page=page,
                    )
                    return BrowserRunResult(
                        status="needs_login",
                        message=(
                            "Gemini login was not detected before timeout. Keep the window "
                            "open, finish login manually, then rerun `status` or `login`."
                        ),
                        debug_bundle_path=str(debug_bundle),
                        selector_report=selector_report,
                    )
                finally:
                    context.close()
        except Exception as exc:
            debug_bundle = self._write_debug_bundle(
                console_messages=console_messages,
                selector_report=selector_report,
                label="login-failure",
                page=None,
            )
            return BrowserRunResult(
                status="backend_blocker",
                message=f"Gemini browser login flow failed: {exc}",
                debug_bundle_path=str(debug_bundle),
                selector_report=selector_report,
            )

    def render_image(
        self,
        *,
        prompt: str,
        output_path: Path,
        aspect_ratio: str = "16:9",
        timeout_sec: int | None = None,
    ) -> BrowserRunResult:
        if sync_playwright is None:
            return BrowserRunResult(
                status="playwright_missing",
                message=(
                    "Playwright is not installed. Run "
                    "`python3 tools/ensure_paper_runtime.py --phase illustration` "
                    "or inspect refine-logs/PAPER_RUNTIME_STATE.json."
                ),
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        timeout = int(timeout_sec or self.config.browser_timeout_sec)
        console_messages: list[dict[str, Any]] = []
        selector_report: dict[str, Any] = {}

        try:
            with sync_playwright() as playwright:
                context = self._launch_context(
                    playwright,
                    headless=self.config.browser_headless,
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    self._attach_console_logging(page, console_messages)
                    self._navigate_to_app(page)
                    state, selector_report = self._detect_state(page)
                    if state != "ready":
                        debug_bundle = self._write_debug_bundle(
                            console_messages=console_messages,
                            selector_report=selector_report,
                            label="render-needs-login",
                            page=page,
                        )
                        return BrowserRunResult(
                            status="needs_login" if state == "needs_login" else "backend_blocker",
                            message=(
                                "Gemini login is required before browser rendering can continue."
                                if state == "needs_login"
                                else "Gemini browser page loaded but prompt box could not be confirmed."
                            ),
                            debug_bundle_path=str(debug_bundle),
                            selector_report=selector_report,
                        )

                    baseline = self._collect_visual_candidates(page)
                    selector_report["baseline_visual_candidates"] = baseline
                    self._submit_prompt(page, prompt)
                    artifact = self._wait_for_generated_artifact(
                        page=page,
                        baseline=baseline,
                        timeout_sec=timeout,
                        selector_report=selector_report,
                    )
                    method = self._save_artifact(
                        page=page,
                        artifact=artifact,
                        output_path=output_path,
                    )
                    return BrowserRunResult(
                        status="auto_illustrated",
                        message=f"Rendered image saved to {output_path}.",
                        output_path=str(output_path),
                        artifact_method=method,
                        selector_report=selector_report,
                    )
                finally:
                    context.close()
        except Exception as exc:
            debug_bundle = self._write_debug_bundle(
                console_messages=console_messages,
                selector_report=selector_report,
                label="render-failure",
                page=locals().get("page"),
            )
            return BrowserRunResult(
                status="backend_blocker",
                message=f"Gemini browser rendering failed: {exc}",
                debug_bundle_path=str(debug_bundle),
                selector_report=selector_report,
            )

    def build_prompt(
        self,
        *,
        method_context: str,
        figure_id: str,
        figure_type: str,
        figure_caption: str,
        figure_description: str,
        references: list[dict[str, Any]],
        aspect_ratio: str,
    ) -> str:
        prompt_lines = [
            "Generate one publication-quality academic figure for an ML paper.",
            f"Figure ID: {figure_id}",
            f"Figure type: {figure_type}",
            f"Aspect ratio target: {aspect_ratio}",
            "",
            "Figure goal:",
            figure_description.strip(),
            "",
            "Caption to support:",
            figure_caption.strip(),
            "",
            "Method context:",
            method_context.strip(),
            "",
            "Style requirements:",
        ]
        prompt_lines.extend(f"- {rule}" for rule in STYLE_RULES)
        prompt_lines.extend(
            [
                "",
                "Additional academic style guide context:",
                self._compact_style_guide(),
            ]
        )
        if references:
            prompt_lines.extend(["", "Reference examples to borrow layout intuition from:"])
            for idx, reference in enumerate(references[:3], start=1):
                title = reference.get("title") or reference.get("id") or f"reference-{idx}"
                prompt_lines.append(f"{idx}. {title}")
                for key in ("caption", "summary", "description", "visual_intent"):
                    value = reference.get(key)
                    if value:
                        prompt_lines.append(f"   - {key}: {value}")
        prompt_lines.extend(
            [
                "",
                "Important constraints:",
                "- The image itself must not contain a paper title or caption block.",
                "- Use clear module names, connectors, grouping boxes, and arrow directions.",
                "- Avoid hand-drawn, photorealistic, or poster-like aesthetics.",
                "- Make the figure readable when embedded in a conference PDF.",
                "",
                "Return only the generated image.",
            ]
        )
        return "\n".join(prompt_lines).strip()

    def _compact_style_guide(self) -> str:
        lines = []
        for raw_line in self.style_guide.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith(("-", "*")) or stripped.startswith("##"):
                lines.append(stripped)
            if len("\n".join(lines)) > 2500:
                break
        return "\n".join(lines[:40]).strip()

    def _launch_context(self, playwright, *, headless: bool):
        kwargs: dict[str, Any] = {
            "user_data_dir": str(self.config.browser_profile_dir),
            "headless": headless,
            "accept_downloads": True,
            "viewport": {"width": 1440, "height": 1080},
        }
        if self.config.browser_channel:
            kwargs["channel"] = self.config.browser_channel
        return playwright.chromium.launch_persistent_context(**kwargs)

    def _navigate_to_app(self, page) -> None:
        page.goto(
            self.config.browser_app_url,
            wait_until="domcontentloaded",
            timeout=self.config.browser_timeout_sec * 1000,
        )
        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=min(self.config.browser_timeout_sec, 30) * 1000,
            )
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(1200)

    def _detect_state(self, page) -> tuple[str, dict[str, Any]]:
        selector_report: dict[str, Any] = {
            "url": page.url,
            "title": page.title(),
        }
        prompt_box = self._find_prompt_box(page)
        selector_report["prompt_box_selector"] = prompt_box[0] if prompt_box else None
        if prompt_box is not None:
            return "ready", selector_report

        selector_report["login_hints"] = self._collect_login_hints(page)
        if "accounts.google.com" in page.url or selector_report["login_hints"]:
            return "needs_login", selector_report

        return "backend_blocker", selector_report

    def _collect_login_hints(self, page) -> list[str]:
        hints = []
        for selector in LOGIN_HINT_SELECTORS:
            locator = page.locator(selector)
            try:
                if locator.count() > 0 and locator.first.is_visible():
                    hints.append(selector)
            except Exception:
                continue
        try:
            if page.get_by_text(SIGN_IN_REGEX).first.is_visible():
                hints.append("text:sign-in")
        except Exception:
            pass
        return hints

    def _find_prompt_box(self, page):
        for selector in PROMPT_BOX_SELECTORS:
            locator = page.locator(selector)
            try:
                count = min(locator.count(), 5)
            except Exception:
                continue
            for idx in range(count):
                candidate = locator.nth(idx)
                try:
                    if candidate.is_visible():
                        return selector, candidate
                except Exception:
                    continue
        return None

    def _submit_prompt(self, page, prompt: str) -> None:
        located = self._find_prompt_box(page)
        if located is None:
            raise RuntimeError("Could not locate the Gemini prompt box.")
        _, prompt_box = located
        prompt_box.click()
        try:
            prompt_box.fill(prompt)
        except Exception:
            prompt_box.evaluate(
                """(el, value) => {
                    el.focus();
                    if ("value" in el) {
                        el.value = value;
                    } else {
                        el.textContent = value;
                    }
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                }""",
                prompt,
            )

        submit_candidates = [
            page.get_by_role("button", name=SUBMIT_BUTTON_REGEX),
            page.locator('button[type="submit"]'),
            page.locator('button[aria-label*="Send" i]'),
            page.locator('button[aria-label*="Run" i]'),
            page.locator('button[aria-label*="Generate" i]'),
            page.locator('button[aria-label*="Create" i]'),
        ]
        for locator in submit_candidates:
            try:
                if locator.count() > 0 and locator.first.is_visible() and locator.first.is_enabled():
                    locator.first.click()
                    return
            except Exception:
                continue
        page.keyboard.press("Enter")

    def _wait_for_generated_artifact(
        self,
        *,
        page,
        baseline: list[dict[str, Any]],
        timeout_sec: int,
        selector_report: dict[str, Any],
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        baseline_signatures = {item["signature"] for item in baseline}
        while time.time() < deadline:
            state, login_report = self._detect_state(page)
            selector_report["state_during_wait"] = login_report
            if state == "needs_login":
                raise RuntimeError("Gemini login expired during image generation.")
            candidates = self._collect_visual_candidates(page)
            selector_report["visual_candidates"] = candidates
            for candidate in candidates:
                if candidate["signature"] not in baseline_signatures:
                    return candidate
            page.wait_for_timeout(2000)
        raise RuntimeError("Timed out waiting for Gemini to generate an image.")

    def _collect_visual_candidates(self, page) -> list[dict[str, Any]]:
        payload = page.evaluate(
            """() => {
                const collect = (selector, kind) => {
                    return Array.from(document.querySelectorAll(selector))
                        .map((el, index) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            const src = kind === "img" ? (el.currentSrc || el.src || "") : "";
                            return {
                                kind,
                                dom_index: index,
                                width: Math.round(rect.width),
                                height: Math.round(rect.height),
                                visible: rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none",
                                src,
                            };
                        })
                        .filter((item) => item.visible && item.width >= 256 && item.height >= 256);
                };
                return collect("main img", "img").concat(collect("main canvas", "canvas"));
            }"""
        )
        candidates = []
        for item in payload:
            signature = f"{item['kind']}:{item['dom_index']}:{item.get('src', '')[:120]}:{item['width']}x{item['height']}"
            candidates.append({**item, "signature": signature})
        return candidates

    def _save_artifact(self, *, page, artifact: dict[str, Any], output_path: Path) -> str:
        if self._try_download_button(page, output_path):
            return "download_button"

        if artifact["kind"] == "img":
            locator = page.locator("main img").nth(int(artifact["dom_index"]))
            src = locator.get_attribute("src") or ""
            if src:
                try:
                    self._write_image_source(page, src, output_path)
                    return "image_source"
                except Exception:
                    locator.screenshot(path=str(output_path), type="png")
                    return "element_screenshot"

        if artifact["kind"] == "canvas":
            page.locator("main canvas").nth(int(artifact["dom_index"])).screenshot(
                path=str(output_path),
                type="png",
            )
            return "canvas_screenshot"

        raise RuntimeError("No supported Gemini image artifact could be saved.")

    def _try_download_button(self, page, output_path: Path) -> bool:
        try:
            buttons = page.get_by_role("button", name=DOWNLOAD_BUTTON_REGEX)
            count = min(buttons.count(), 5)
        except Exception:
            return False
        for idx in range(count):
            button = buttons.nth(idx)
            try:
                if not button.is_visible() or not button.is_enabled():
                    continue
                with page.expect_download(timeout=5000) as download_info:
                    button.click()
                download = download_info.value
                download.save_as(str(output_path))
                return True
            except Exception:
                continue
        return False

    def _write_image_source(self, page, src: str, output_path: Path) -> None:
        if src.startswith("data:"):
            _, encoded = src.split(",", 1)
            output_path.write_bytes(base64.b64decode(encoded))
            return

        byte_values = page.evaluate(
            """async (url) => {
                const response = await fetch(url);
                const buffer = await response.arrayBuffer();
                return Array.from(new Uint8Array(buffer));
            }""",
            src,
        )
        output_path.write_bytes(bytes(byte_values))

    def _attach_console_logging(self, page, console_messages: list[dict[str, Any]]) -> None:
        def handle_console(message) -> None:
            console_messages.append(
                {
                    "type": message.type,
                    "text": message.text,
                }
            )

        page.on("console", handle_console)

    def _write_debug_bundle(
        self,
        *,
        console_messages: list[dict[str, Any]],
        selector_report: dict[str, Any],
        label: str,
        page,
    ) -> Path:
        bundle_dir = (
            Path(self.config.browser_debug_dir)
            / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{label}-{uuid.uuid4().hex[:8]}"
        )
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "console.json").write_text(
            json.dumps(console_messages, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (bundle_dir / "selector_report.json").write_text(
            json.dumps(selector_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if page is not None:
            try:
                page.screenshot(path=str(bundle_dir / "page.png"), full_page=True)
            except Exception:
                pass
            try:
                (bundle_dir / "page.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
        return bundle_dir
