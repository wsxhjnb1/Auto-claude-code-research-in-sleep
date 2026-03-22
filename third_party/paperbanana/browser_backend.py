# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived for ARIS browser-backed Gemini illustration runtime.

from __future__ import annotations

import base64
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
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
    "textarea",
    'div[contenteditable="true"][role="textbox"]',
    'div[contenteditable="true"]',
]

LOGIN_HINT_SELECTORS = [
    'input[type="email"]',
    'input[type="password"]',
    'form[action*="accounts"]',
]

DOWNLOAD_BUTTON_REGEX = re.compile(
    r"(download|download full.*image|save image|save|下载|保存)",
    re.IGNORECASE,
)

SUBMIT_BUTTON_REGEX = re.compile(
    r"(send|submit|run|generate|create|生成|发送|运行)",
    re.IGNORECASE,
)
TRUSTED_SUBMIT_REGEX = re.compile(r"^(send|submit|发送)$", re.IGNORECASE)

SIGN_IN_REGEX = re.compile(r"(sign in|登录|登入)", re.IGNORECASE)
TOOLS_BUTTON_REGEX = re.compile(r"(tools|工具)", re.IGNORECASE)
MODE_PICKER_REGEX = re.compile(r"(open mode picker|打开模式选择器|fast|flash|pro|思考|thinking)", re.IGNORECASE)
MODE_PICKER_OPEN_REGEX = re.compile(r"(open mode picker|打开模式选择器|change model|switch model|模式选择器)", re.IGNORECASE)
THINKING_MODE_REGEX = re.compile(r"(thinking|思考|pro\b|2\.?5 pro)", re.IGNORECASE)
FAST_MODE_REGEX = re.compile(r"(fast|flash|快速|2\.?5 flash)", re.IGNORECASE)
IMAGE_MODE_REGEX = re.compile(
    r"(制作图片|create images?|generate images?|make image|image generation|生成图片|创建图片|image|images|imagen|photo)",
    re.IGNORECASE,
)
IMAGE_TOOL_ACTIVE_REGEX = re.compile(
    r"(cancel select.*(image|制作图片)|取消选择.?制作图片.?)",
    re.IGNORECASE,
)
TEMPORARY_CHAT_REGEX = re.compile(
    r"(temporary conversation|temporary chat|临时对话)",
    re.IGNORECASE,
)
NEW_CHAT_REGEX = re.compile(
    r"(new chat|new conversation|发起新对话|新对话)",
    re.IGNORECASE,
)
LOGIN_REQUIRED_TEXT_REGEX = re.compile(
    r"(sign in to .*create images|sign in to connect to google apps, create images, and more|signed out|you're signed out|you are signed out)",
    re.IGNORECASE,
)
HUMAN_VERIFICATION_TEXT_REGEX = re.compile(
    r"(i(?:'| a)?m not a robot|我不是机器人|verify (?:that )?you(?:'re| are)? human|confirm (?:that )?you(?:'re| are)? not a bot|complete (?:the )?(?:captcha|verification)|human verification|security check|unusual traffic|recaptcha|captcha|sorry)",
    re.IGNORECASE,
)
CAPTCHA_URL_REGEX = re.compile(
    r"(?:/sorry(?:/|$)|recaptcha|captcha|challenge)",
    re.IGNORECASE,
)
IMAGE_UNAVAILABLE_TEXT_REGEX = re.compile(
    r"(can't create it right now|image creation isn't available|image generation isn't available|not available in your location|not available in your region)",
    re.IGNORECASE,
)
HISTORY_TRANSFORMER_REGEX = re.compile(
    r"(transformer|attention|kv cache|架构图|方法的技术细节|数学严谨性)",
    re.IGNORECASE,
)
HOME_SURFACE_REGEX = re.compile(
    r"(需要我为你做些什么|what can i help with|与 gemini 对话|talk to gemini)",
    re.IGNORECASE,
)
ACTIVE_CONTROL_STATE_VALUES = {"true", "active", "selected", "checked", "on"}

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


class BrowserStateError(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class BrowserPageSession:
    mode: str
    page: Any
    context: Any | None = None
    browser: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InteractiveLoginResult:
    status: str
    message: str
    selector_report: dict[str, Any]
    session: BrowserPageSession | None = None


class GeminiBrowserBackend:
    """Browser-backed renderer that reuses a dedicated Gemini web profile."""

    def __init__(self, config: IllustrationConfig) -> None:
        self.config = config
        self._runtime_state_cache: dict[str, Any] | None = None
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
        playwright = sync_playwright().start()
        session: BrowserPageSession | None = None
        page = None
        try:
            session = self._open_preflight_session(
                playwright,
                console_messages=console_messages,
                headless=self.config.browser_headless,
                reason="status",
            )
            page = session.page
            state, selector_report = self._detect_state(page)
            selector_report["profile_exists"] = profile_exists
            selector_report["profile_dir"] = str(self.config.browser_profile_dir)

            if self.config.browser_auto_interactive and session.mode == "cdp":
                login_result = self._ensure_interactive_login_session(
                    playwright,
                    console_messages=console_messages,
                    wait_sec=self.config.browser_auto_interactive_wait_sec,
                    current_session=session,
                    reason="status",
                )
                session = login_result.session
                page = session.page if session is not None else page
                selector_report = login_result.selector_report
                selector_report["profile_exists"] = profile_exists
                selector_report["profile_dir"] = str(self.config.browser_profile_dir)
                return BrowserRunResult(
                    status=login_result.status,
                    message=login_result.message,
                    selector_report=selector_report,
                )
            if (
                state in {"needs_login", "needs_human_verification"}
                and self.config.browser_auto_interactive
            ):
                login_result = self._ensure_interactive_login_session(
                    playwright,
                    console_messages=console_messages,
                    wait_sec=self.config.browser_auto_interactive_wait_sec,
                    current_session=session,
                    reason="status",
                )
                session = login_result.session
                page = session.page if session is not None else page
                selector_report = login_result.selector_report
                selector_report["profile_exists"] = profile_exists
                selector_report["profile_dir"] = str(self.config.browser_profile_dir)
                return BrowserRunResult(
                    status=login_result.status,
                    message=login_result.message,
                    selector_report=selector_report,
                )

            return BrowserRunResult(
                status=state,
                message=self._state_message(state, selector_report),
                selector_report=selector_report,
            )
        except BrowserStateError as exc:
            debug_bundle = self._write_debug_bundle(
                console_messages=console_messages,
                selector_report=selector_report,
                label="status-state",
                page=page,
            )
            return BrowserRunResult(
                status=exc.status,
                message=exc.message,
                debug_bundle_path=str(debug_bundle),
                selector_report=selector_report,
            )
        except Exception as exc:
            debug_bundle = self._write_debug_bundle(
                console_messages=console_messages,
                selector_report=selector_report,
                label="status-failure",
                page=page,
            )
            return BrowserRunResult(
                status="backend_blocker",
                message=f"Gemini browser status check failed: {exc}",
                debug_bundle_path=str(debug_bundle),
                selector_report=selector_report,
            )
        finally:
            self._close_page_session(session)
            self._stop_playwright(playwright)

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
        timeout = int(timeout_sec or self.config.browser_auto_interactive_wait_sec)
        console_messages: list[dict[str, Any]] = []
        selector_report: dict[str, Any] = {
            "profile_dir": str(self.config.browser_profile_dir),
        }
        playwright = sync_playwright().start()
        session: BrowserPageSession | None = None
        page = None
        try:
            login_result = self._ensure_interactive_login_session(
                playwright,
                console_messages=console_messages,
                wait_sec=timeout,
                current_session=None,
                reason="login",
            )
            session = login_result.session
            page = session.page if session is not None else None
            selector_report = login_result.selector_report
            return BrowserRunResult(
                status=login_result.status,
                message=login_result.message,
                selector_report=selector_report,
            )
        except Exception as exc:
            debug_bundle = self._write_debug_bundle(
                console_messages=console_messages,
                selector_report=selector_report,
                label="login-failure",
                page=page,
            )
            return BrowserRunResult(
                status="backend_blocker",
                message=f"Gemini browser login flow failed: {exc}",
                debug_bundle_path=str(debug_bundle),
                selector_report=selector_report,
            )
        finally:
            self._close_page_session(session)
            self._stop_playwright(playwright)

    def render_image(
        self,
        *,
        prompt: str,
        output_path: Path,
        aspect_ratio: str = "16:9",
        timeout_sec: int | None = None,
        login_timeout_sec: int | None = None,
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
        login_timeout = int(login_timeout_sec or self.config.browser_auto_interactive_wait_sec)
        browser_prompt = self._build_browser_prompt(prompt, aspect_ratio)
        console_messages: list[dict[str, Any]] = []
        selector_report: dict[str, Any] = {}
        playwright = sync_playwright().start()
        session: BrowserPageSession | None = None
        page = None
        try:
            session = self._open_preflight_session(
                playwright,
                console_messages=console_messages,
                headless=self.config.browser_headless,
                reason="render_image",
            )
            page = session.page
            state, selector_report = self._detect_state(page)
            if self.config.browser_auto_interactive and session.mode == "cdp":
                login_result = self._ensure_interactive_login_session(
                    playwright,
                    console_messages=console_messages,
                    wait_sec=login_timeout,
                    current_session=session,
                    reason="render_image",
                )
                session = login_result.session
                page = session.page if session is not None else page
                selector_report = login_result.selector_report
                if login_result.status != "ready":
                    debug_bundle = self._write_debug_bundle(
                        console_messages=console_messages,
                        selector_report=selector_report,
                        label="render-recovery-wait",
                        page=page,
                    )
                    return BrowserRunResult(
                        status=login_result.status,
                        message=login_result.message,
                        debug_bundle_path=str(debug_bundle),
                        selector_report=selector_report,
                    )
                state = "ready"
            elif (
                state in {"needs_login", "needs_human_verification"}
                and self.config.browser_auto_interactive
            ):
                login_result = self._ensure_interactive_login_session(
                    playwright,
                    console_messages=console_messages,
                    wait_sec=login_timeout,
                    current_session=session,
                    reason="render_image",
                )
                session = login_result.session
                page = session.page if session is not None else page
                selector_report = login_result.selector_report
                if login_result.status != "ready":
                    debug_bundle = self._write_debug_bundle(
                        console_messages=console_messages,
                        selector_report=selector_report,
                        label="render-recovery-wait",
                        page=page,
                    )
                    return BrowserRunResult(
                        status=login_result.status,
                        message=login_result.message,
                        debug_bundle_path=str(debug_bundle),
                        selector_report=selector_report,
                    )
                state = "ready"

            if state != "ready":
                debug_bundle = self._write_debug_bundle(
                    console_messages=console_messages,
                    selector_report=selector_report,
                    label="render-preflight",
                    page=page,
                )
                return BrowserRunResult(
                    status=state,
                    message=self._state_message(state, selector_report),
                    debug_bundle_path=str(debug_bundle),
                    selector_report=selector_report,
                )
            selector_report["context_contamination_detected"] = False
            selector_report["render_retry_count"] = 0
            retry_limit = (
                max(self.config.browser_render_max_retries, 0)
                if self.config.browser_retry_on_context_leak
                else 0
            )
            retry_reasons: list[str] = []
            last_contamination_message: str | None = None
            session_mode_override: str | None = None

            for attempt_idx in range(retry_limit + 1):
                selector_report["render_attempt"] = attempt_idx + 1
                page = self._prune_session_pages(
                    session,
                    console_messages=console_messages,
                    selector_report=selector_report,
                    report_prefix="interactive" if session.mode == "cdp" else "background",
                )
                self._reset_render_session(
                    page,
                    selector_report,
                    session_mode_override=session_mode_override,
                )
                self._prepare_image_generation_mode(page, selector_report)
                self._prepare_model_mode(page, selector_report)
                blocker = self._detect_page_blocker(page, selector_report)
                if blocker is not None:
                    debug_bundle = self._write_debug_bundle(
                        console_messages=console_messages,
                        selector_report=selector_report,
                        label="render-blocked",
                        page=page,
                    )
                    return BrowserRunResult(
                        status=blocker[0],
                        message=blocker[1],
                        debug_bundle_path=str(debug_bundle),
                        selector_report=selector_report,
                    )

                baseline_visual = self._collect_visual_candidates(page)
                baseline_downloads = self._collect_download_candidates(page)
                selector_report["baseline_visual_candidates"] = baseline_visual
                selector_report["baseline_download_candidates"] = baseline_downloads
                contamination_message = self._detect_context_contamination(
                    selector_report=selector_report,
                    baseline_visual=baseline_visual,
                    baseline_downloads=baseline_downloads,
                )
                if contamination_message is not None:
                    selector_report["context_contamination_detected"] = True
                    selector_report["render_retry_count"] = attempt_idx + 1
                    retry_reasons.append(contamination_message)
                    if attempt_idx < retry_limit:
                        if selector_report.get("session_reset_mode") == "temporary":
                            session_mode_override = "new_chat"
                        continue
                    last_contamination_message = contamination_message
                    break

                self._submit_prompt(page, browser_prompt, selector_report)
                try:
                    artifact = self._wait_for_generated_artifact(
                        page=page,
                        baseline_visual=baseline_visual,
                        baseline_downloads=baseline_downloads,
                        timeout_sec=timeout,
                        selector_report=selector_report,
                    )
                except BrowserStateError as exc:
                    retry_reasons.append(exc.message)
                    if (
                        attempt_idx < retry_limit
                        and selector_report.get("session_reset_mode") == "temporary"
                        and "Timed out waiting for Gemini to generate an image." in exc.message
                    ):
                        session_mode_override = "new_chat"
                        selector_report["render_retry_count"] = attempt_idx + 1
                        continue
                    raise
                contamination_message = self._detect_context_contamination(
                    selector_report=selector_report,
                    baseline_visual=baseline_visual,
                    baseline_downloads=baseline_downloads,
                )
                if contamination_message is not None:
                    selector_report["context_contamination_detected"] = True
                    selector_report["render_retry_count"] = attempt_idx + 1
                    retry_reasons.append(contamination_message)
                    if attempt_idx < retry_limit:
                        if selector_report.get("session_reset_mode") == "temporary":
                            session_mode_override = "new_chat"
                        continue
                    last_contamination_message = contamination_message
                    break

                method = self._save_artifact(
                    page=page,
                    artifact=artifact,
                    output_path=output_path,
                )
                selector_report["render_retry_reasons"] = retry_reasons
                return BrowserRunResult(
                    status="auto_illustrated",
                    message=f"Rendered image saved to {output_path}.",
                    output_path=str(output_path),
                    artifact_method=method,
                    selector_report=selector_report,
                )

            selector_report["render_retry_reasons"] = retry_reasons
            raise BrowserStateError(
                "backend_blocker",
                last_contamination_message
                or "Gemini browser render kept inheriting stale context after automatic session reset.",
            )
        except BrowserStateError as exc:
            debug_bundle = self._write_debug_bundle(
                console_messages=console_messages,
                selector_report=selector_report,
                label="render-state",
                page=page,
            )
            return BrowserRunResult(
                status=exc.status,
                message=exc.message,
                debug_bundle_path=str(debug_bundle),
                selector_report=selector_report,
            )
        except Exception as exc:
            debug_bundle = self._write_debug_bundle(
                console_messages=console_messages,
                selector_report=selector_report,
                label="render-failure",
                page=page,
            )
            return BrowserRunResult(
                status="backend_blocker",
                message=f"Gemini browser rendering failed: {exc}",
                debug_bundle_path=str(debug_bundle),
                selector_report=selector_report,
            )
        finally:
            self._close_page_session(session)
            self._stop_playwright(playwright)

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

    def _build_browser_prompt(self, prompt: str, aspect_ratio: str) -> str:
        cleaned = " ".join(prompt.split())
        instructions = [
            "Generate a single image only.",
            "Do not answer with text.",
            "Do not describe the image.",
            "Return only the final image.",
        ]
        if aspect_ratio:
            instructions.append(f"Use aspect ratio {aspect_ratio}.")
        return " ".join(instructions + [cleaned]).strip()

    def _ensure_browser_runtime_ready(self) -> dict[str, Any]:
        if self._runtime_state_cache is not None:
            return self._runtime_state_cache
        try:
            from tools.ensure_paper_runtime import ensure_runtime
        except Exception:
            self._runtime_state_cache = {}
            return self._runtime_state_cache
        self._runtime_state_cache = ensure_runtime(
            "illustration",
            work_dir=self.config.work_dir,
        )
        return self._runtime_state_cache

    def _current_playwright_browser_state(self) -> dict[str, Any]:
        runtime_state = self._ensure_browser_runtime_ready()
        payload = runtime_state.get("playwright_browser", {})
        return payload if isinstance(payload, dict) else {}

    def _open_local_session(
        self,
        playwright,
        *,
        console_messages: list[dict[str, Any]],
        headless: bool,
    ) -> BrowserPageSession:
        self._ensure_browser_runtime_ready()
        context = self._launch_context(playwright, headless=headless)
        metadata: dict[str, Any] = {}
        page = self._prune_context_pages(
            context,
            selector_report=metadata,
            report_prefix="background",
        )
        self._attach_console_logging(page, console_messages)
        self._navigate_to_app(page)
        metadata["background_pages_after_prune"] = [
            self._snapshot_budget_page(page, preferred=True)
        ]
        metadata["background_kept_page_url"] = page.url or ""
        return BrowserPageSession(
            mode="persistent",
            page=page,
            context=context,
            metadata={
                "background_session_started": bool(headless),
                **metadata,
            },
        )

    def _open_preflight_session(
        self,
        playwright,
        *,
        console_messages: list[dict[str, Any]],
        headless: bool,
        reason: str,
    ) -> BrowserPageSession:
        browser_state = self._current_playwright_browser_state()
        if self.config.browser_auto_interactive:
            session_state, reused = self._launch_or_reuse_interactive_session()
            return self._connect_interactive_session(
                playwright,
                session_state=session_state,
                console_messages=console_messages,
                reused=reused,
                reason=reason,
            )
        session_state = self._read_session_state()
        if self._session_state_is_usable(session_state, browser_state=browser_state):
            return self._connect_interactive_session(
                playwright,
                session_state=session_state,
                console_messages=console_messages,
                reused=True,
                reason=reason,
            )
        return self._open_local_session(
            playwright,
            console_messages=console_messages,
            headless=headless,
        )

    def _ensure_interactive_login_session(
        self,
        playwright,
        *,
        console_messages: list[dict[str, Any]],
        wait_sec: int,
        current_session: BrowserPageSession | None,
        reason: str,
    ) -> InteractiveLoginResult:
        if current_session is not None and current_session.mode == "cdp":
            session = current_session
            selector_report = dict(session.metadata)
        else:
            self._close_page_session(current_session)
            session_state, reused = self._launch_or_reuse_interactive_session()
            session = self._connect_interactive_session(
                playwright,
                session_state=session_state,
                console_messages=console_messages,
                reused=reused,
                reason=reason,
            )
            selector_report = dict(session.metadata)
        selector_report["interactive_wait_seconds"] = wait_sec
        recoverable_states = {"needs_login"}
        if self.config.browser_auto_wait_for_human_verification:
            recoverable_states.add("needs_human_verification")
        last_waiting_status = "needs_login"

        deadline = time.time() + max(wait_sec, 0)
        while True:
            self._prune_session_pages(
                session,
                console_messages=console_messages,
                selector_report=selector_report,
                report_prefix="interactive",
            )
            state, state_report = self._detect_state(session.page)
            selector_report.update(state_report)
            blocker = self._detect_page_blocker(session.page, selector_report)
            if state == "ready":
                selector_report["interactive_state"] = "ready"
                if (
                    self.config.browser_close_interactive_after_ready
                    and session.mode == "cdp"
                ):
                    try:
                        session = self._handoff_interactive_session_to_background(
                            playwright,
                            session=session,
                            console_messages=console_messages,
                            selector_report=selector_report,
                        )
                    except BrowserStateError as exc:
                        selector_report["interactive_handoff_performed"] = False
                        selector_report["background_session_started"] = False
                        selector_report["interactive_handoff_error"] = exc.message
                        recovery_session: BrowserPageSession | None = None
                        try:
                            recovery_state, recovery_reused = (
                                self._launch_or_reuse_interactive_session()
                            )
                            recovery_session = self._connect_interactive_session(
                                playwright,
                                session_state=recovery_state,
                                console_messages=console_messages,
                                reused=recovery_reused,
                                reason=f"{reason}:handoff_recovery",
                            )
                            selector_report.update(recovery_session.metadata)
                        except Exception as recovery_exc:
                            selector_report["interactive_handoff_recovery_error"] = str(
                                recovery_exc
                            )
                        return InteractiveLoginResult(
                            status="backend_blocker",
                            message=exc.message,
                            selector_report=selector_report,
                            session=recovery_session,
                        )
                return InteractiveLoginResult(
                    status="ready",
                    message=(
                        "Gemini login is ready and the dedicated profile is available "
                        f"at {self.config.browser_profile_dir}."
                    ),
                    selector_report=selector_report,
                    session=session,
                )
            waiting_status = None
            if blocker is not None and blocker[0] in {"needs_login", "needs_human_verification"}:
                waiting_status = blocker[0]
            elif state in {"needs_login", "needs_human_verification"}:
                waiting_status = state

            if waiting_status is not None:
                last_waiting_status = waiting_status
                selector_report["interactive_state"] = waiting_status
                if (
                    waiting_status == "needs_human_verification"
                    and not self.config.browser_auto_wait_for_human_verification
                ):
                    return InteractiveLoginResult(
                        status=waiting_status,
                        message=self._interactive_wait_message(
                            waiting_status,
                            wait_sec,
                            timed_out=False,
                        ),
                        selector_report=selector_report,
                        session=session,
                    )

            if blocker is not None and blocker[0] not in recoverable_states:
                selector_report["interactive_state"] = blocker[0]
                return InteractiveLoginResult(
                    status=blocker[0],
                    message=blocker[1],
                    selector_report=selector_report,
                    session=session,
                )
            if time.time() >= deadline:
                selector_report["interactive_state"] = last_waiting_status
                return InteractiveLoginResult(
                    status=last_waiting_status,
                    message=self._interactive_wait_message(
                        last_waiting_status,
                        wait_sec,
                        timed_out=True,
                    ),
                    selector_report=selector_report,
                    session=session,
                )
            session.page.wait_for_timeout(1500)

    def _launch_or_reuse_interactive_session(self) -> tuple[dict[str, Any], bool]:
        self._ensure_gui_available()
        browser_state = self._current_playwright_browser_state()
        self.config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        session_state = self._read_session_state()
        if self._session_state_is_usable(session_state, browser_state=browser_state):
            return session_state, True
        if session_state is not None:
            self._terminate_interactive_session(session_state)

        executable, executable_meta = self._resolve_browser_executable(browser_state)
        port = self._find_available_port(self.config.browser_remote_debug_port)
        log_path = Path(self.config.browser_launch_log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        argv = [
            str(executable),
            f"--user-data-dir={self.config.browser_profile_dir}",
            f"--remote-debugging-port={port}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            self.config.browser_app_url,
        ]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            argv.insert(-1, "--no-sandbox")

        with log_path.open("ab") as log_file:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ.copy(),
            )

        session_state = {
            "pid": process.pid,
            "port": port,
            "profile_dir": str(self.config.browser_profile_dir),
            "log_path": str(log_path),
            "launched_at": self._utc_now(),
            "browser_app_url": self.config.browser_app_url,
            "browser_executable": str(executable),
            "browser_managed": executable_meta["managed"],
            "browser_revision": executable_meta["revision"],
            "browser_source": executable_meta["source"],
        }
        self._wait_for_debug_endpoint(port=port, pid=process.pid, log_path=log_path)
        self._write_session_state(session_state)
        return session_state, False

    def _connect_interactive_session(
        self,
        playwright,
        *,
        session_state: dict[str, Any],
        console_messages: list[dict[str, Any]],
        reused: bool,
        reason: str,
    ) -> BrowserPageSession:
        browser = playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{session_state['port']}"
        )
        if not browser.contexts:
            raise BrowserStateError(
                "backend_blocker",
                "The interactive Gemini browser session exposed no attachable context.",
            )
        context = browser.contexts[0]
        metadata = {
            "auto_interactive_triggered": True,
            "interactive_session_reused": reused,
            "interactive_browser_pid": session_state.get("pid"),
            "interactive_debug_port": session_state.get("port"),
            "interactive_log_path": session_state.get("log_path"),
            "interactive_reason": reason,
            "interactive_browser_revision": session_state.get("browser_revision"),
            "interactive_browser_managed": session_state.get("browser_managed"),
        }
        page = self._prune_context_pages(
            context,
            selector_report=metadata,
            report_prefix="interactive",
        )
        self._attach_console_logging(page, console_messages)
        current_url = page.url or ""
        if not current_url or current_url == "about:blank":
            self._navigate_to_app(page)
        else:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            try:
                page.wait_for_timeout(800)
            except Exception:
                pass
        return BrowserPageSession(
            mode="cdp",
            page=page,
            context=context,
            browser=browser,
            metadata=metadata,
        )

    def _select_interactive_page(self, context):
        if context.pages:
            for page in context.pages:
                if "gemini.google.com" in (page.url or ""):
                    return page
            return context.pages[0]
        return context.new_page()

    def _prune_session_pages(
        self,
        session: BrowserPageSession,
        *,
        console_messages: list[dict[str, Any]],
        selector_report: dict[str, Any],
        report_prefix: str,
    ) -> Any:
        if session.context is None:
            return session.page
        page = self._prune_context_pages(
            session.context,
            selector_report=selector_report,
            report_prefix=report_prefix,
            preferred_page=session.page,
        )
        if page is not session.page:
            self._attach_console_logging(page, console_messages)
            session.page = page
        return session.page

    def _prune_context_pages(
        self,
        context,
        *,
        selector_report: dict[str, Any],
        report_prefix: str,
        preferred_page=None,
    ):
        pages = [page for page in context.pages if not self._page_is_closed(page)]
        if not pages:
            pages = [context.new_page()]

        snapshots_before = [
            self._snapshot_budget_page(page, preferred=(page is preferred_page))
            for page in pages
        ]
        keep_pages = self._select_budget_pages(
            pages,
            snapshots_before,
            max_pages=self.config.normalized_browser_max_interactive_pages,
        )
        keep_page = keep_pages[0]
        closed_snapshots: list[dict[str, Any]] = []
        prune_performed = False
        if self.config.browser_prune_extra_pages:
            for page, snapshot in zip(pages, snapshots_before):
                if page in keep_pages:
                    continue
                if self._safe_close_page(page):
                    prune_performed = True
                    closed_snapshots.append(snapshot)

        remaining_pages = [page for page in context.pages if not self._page_is_closed(page)]
        if keep_page not in remaining_pages:
            remaining_keep = [page for page in keep_pages if page in remaining_pages]
            if remaining_keep:
                keep_page = remaining_keep[0]
            elif remaining_pages:
                keep_page = remaining_pages[0]
            else:
                keep_page = context.new_page()
                remaining_pages = [keep_page]

        try:
            keep_page.bring_to_front()
        except Exception:
            pass

        snapshots_after = [
            self._snapshot_budget_page(page, preferred=(page is keep_page))
            for page in remaining_pages
        ]
        selector_report[f"{report_prefix}_pages_before_prune"] = snapshots_before
        selector_report[f"{report_prefix}_pages_after_prune"] = snapshots_after
        selector_report[f"{report_prefix}_pages_closed"] = closed_snapshots
        selector_report[f"{report_prefix}_prune_performed"] = prune_performed
        selector_report[f"{report_prefix}_kept_page_url"] = keep_page.url or ""
        return keep_page

    def _select_budget_pages(
        self,
        pages: list[Any],
        snapshots: list[dict[str, Any]],
        *,
        max_pages: int,
    ) -> list[Any]:
        ranked = sorted(
            zip(pages, snapshots),
            key=lambda item: (
                int(item[1].get("priority", 0)),
                int(bool(item[1].get("preferred"))),
            ),
            reverse=True,
        )
        budget = max(max_pages, 1)
        keep = [page for page, _ in ranked[:budget]]
        return keep or [pages[0]]

    def _snapshot_budget_page(
        self,
        page,
        *,
        preferred: bool,
    ) -> dict[str, Any]:
        url = ""
        title = ""
        try:
            url = page.url or ""
        except Exception:
            url = ""
        try:
            title = page.title() or ""
        except Exception:
            title = ""

        excerpt = ""
        if not url or url == "about:blank" or "google." in url or "gemini.google.com" in url:
            try:
                excerpt = self._collect_response_excerpt(page, limit=600)
            except Exception:
                excerpt = ""

        try:
            human_signals = self._collect_human_verification_signals(
                page,
                response_excerpt=excerpt,
                page_title=title,
                page_url=url,
            )
        except Exception:
            human_signals = []

        role = "other"
        priority = 25
        if human_signals:
            role = "human_verification"
            priority = 400
        elif "accounts.google.com" in url or SIGN_IN_REGEX.search(title) or SIGN_IN_REGEX.search(excerpt):
            role = "login"
            priority = 300
        elif "gemini.google.com" in url:
            try:
                prompt_box = self._find_prompt_box(page)
            except Exception:
                prompt_box = None
            role = "gemini_app_ready" if prompt_box is not None else "gemini_app"
            priority = 220 if prompt_box is not None else 200
        elif not url or url == "about:blank":
            role = "blank"
            priority = 0
        elif "google." in url:
            role = "google_other"
            priority = 50

        return {
            "url": url,
            "title": title,
            "role": role,
            "priority": priority,
            "preferred": preferred,
        }

    def _page_is_closed(self, page) -> bool:
        try:
            return bool(page.is_closed())
        except Exception:
            return False

    def _safe_close_page(self, page) -> bool:
        if self._page_is_closed(page):
            return False
        try:
            page.close()
            return True
        except Exception:
            return False

    def _ensure_gui_available(self) -> None:
        if platform.system() != "Linux":
            return
        if os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"):
            return
        raise BrowserStateError(
            "backend_blocker",
            "No GUI display is available for the interactive Gemini login window. "
            "Set DISPLAY/WAYLAND_DISPLAY or use a graphical session.",
        )

    def _handoff_interactive_session_to_background(
        self,
        playwright,
        *,
        session: BrowserPageSession,
        console_messages: list[dict[str, Any]],
        selector_report: dict[str, Any],
    ) -> BrowserPageSession:
        session_state = self._read_session_state() or {
            "pid": session.metadata.get("interactive_browser_pid"),
            "port": session.metadata.get("interactive_debug_port"),
            "log_path": session.metadata.get("interactive_log_path"),
            "profile_dir": str(self.config.browser_profile_dir),
        }
        errors: list[str] = []
        for attempt in range(2):
            try:
                self._close_interactive_browser_process(
                    session=session,
                    session_state=session_state,
                )
                background_session = self._open_local_session(
                    playwright,
                    console_messages=console_messages,
                    headless=True,
                )
                selector_report["interactive_handoff_performed"] = True
                selector_report["interactive_handoff_attempt"] = attempt + 1
                selector_report["background_session_started"] = True
                selector_report["interactive_browser_pid"] = session_state.get("pid")
                selector_report["background_pages_after_handoff"] = (
                    background_session.metadata.get("background_pages_after_prune")
                )
                return background_session
            except Exception as exc:
                errors.append(str(exc))
                selector_report["interactive_handoff_errors"] = errors
                time.sleep(1.0)
        raise BrowserStateError(
            "backend_blocker",
            "Gemini login succeeded, but the browser backend could not close the "
            "interactive window and continue in the background.",
        )

    def _close_interactive_browser_process(
        self,
        *,
        session: BrowserPageSession,
        session_state: dict[str, Any],
    ) -> None:
        pid = int(
            session_state.get("pid")
            or session.metadata.get("interactive_browser_pid")
            or 0
        )
        try:
            if session.browser is not None:
                session.browser.close()
        except Exception:
            pass
        if pid > 0 and not self._wait_for_pid_exit(pid, timeout_sec=10):
            try:
                os.kill(pid, 15)
            except OSError:
                pass
            if not self._wait_for_pid_exit(pid, timeout_sec=5):
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
                self._wait_for_pid_exit(pid, timeout_sec=3)
        self._clear_session_state()

    def _wait_for_pid_exit(self, pid: int, *, timeout_sec: int) -> bool:
        deadline = time.time() + max(timeout_sec, 0)
        while time.time() < deadline:
            if not self._pid_is_alive(pid):
                return True
            time.sleep(0.25)
        return not self._pid_is_alive(pid)

    def _resolve_browser_executable(
        self,
        browser_state: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        if self.config.browser_executable_path is not None:
            executable = Path(self.config.browser_executable_path).expanduser().resolve()
            if executable.exists():
                return executable, {
                    "managed": False,
                    "revision": None,
                    "source": "explicit",
                }
            raise BrowserStateError(
                "backend_blocker",
                f"GEMINI_BROWSER_EXECUTABLE_PATH does not exist: {executable}",
            )

        required_revision = str(browser_state.get("installed_revision") or "").strip()
        for candidate in self._playwright_browser_candidates():
            if not candidate.exists():
                continue
            candidate_revision = self._revision_from_path(candidate)
            if required_revision and candidate_revision != required_revision:
                continue
            return candidate, {
                "managed": True,
                "revision": candidate_revision,
                "source": "playwright",
            }

        system_candidates = [
            shutil.which("google-chrome-stable"),
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        ]
        if platform.system() == "Darwin":
            system_candidates.extend(
                [
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    "/Applications/Chromium.app/Contents/MacOS/Chromium",
                ]
            )
        for raw in system_candidates:
            if not raw:
                continue
            candidate = Path(raw).expanduser()
            if candidate.exists():
                return candidate.resolve(), {
                    "managed": False,
                    "revision": None,
                    "source": "system",
                }

        raise BrowserStateError(
            "backend_blocker",
            "Could not locate a browser executable for the interactive Gemini session. "
            "Install Playwright Chromium or set GEMINI_BROWSER_EXECUTABLE_PATH.",
        )

    def _playwright_browser_candidates(self) -> list[Path]:
        roots: list[Path] = []
        custom_root = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip()
        if custom_root:
            roots.append(Path(custom_root).expanduser())
        roots.append(Path.home() / ".cache" / "ms-playwright")

        patterns = [
            "chromium-*/chrome-linux/chrome",
            "chromium-*/chrome-linux64/chrome",
            "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
            "chromium-*/chrome-win/chrome.exe",
        ]
        candidates: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                candidates.extend(sorted(root.glob(pattern), reverse=True))
        return candidates

    def _find_available_port(self, preferred_port: int) -> int:
        for candidate in range(preferred_port, preferred_port + 20):
            if self._port_is_available(candidate):
                return candidate
        raise BrowserStateError(
            "backend_blocker",
            f"Could not reserve a Gemini browser remote debugging port near {preferred_port}.",
        )

    def _port_is_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def _wait_for_debug_endpoint(self, *, port: int, pid: int, log_path: Path) -> None:
        deadline = time.time() + 20
        last_error = ""
        while time.time() < deadline:
            info = self._probe_debug_endpoint(port)
            if info is not None:
                return
            if not self._pid_is_alive(pid):
                break
            time.sleep(0.5)
        if log_path.exists():
            try:
                last_error = log_path.read_text(encoding="utf-8")[-2000:]
            except Exception:
                last_error = ""
        raise BrowserStateError(
            "backend_blocker",
            "Gemini interactive browser window failed to start a remote debugging "
            f"endpoint on port {port}. {last_error}".strip(),
        )

    def _probe_debug_endpoint(self, port: int) -> dict[str, Any] | None:
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _read_session_state(self) -> dict[str, Any] | None:
        path = Path(self.config.browser_session_state_path)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_session_state(self, payload: dict[str, Any]) -> None:
        path = Path(self.config.browser_session_state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _clear_session_state(self) -> None:
        path = Path(self.config.browser_session_state_path)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            pass

    def _session_state_is_usable(
        self,
        payload: dict[str, Any] | None,
        *,
        browser_state: dict[str, Any],
    ) -> bool:
        if not payload:
            return False
        if payload.get("profile_dir") != str(self.config.browser_profile_dir):
            return False
        if not self._session_state_matches_browser(payload, browser_state=browser_state):
            return False
        pid = int(payload.get("pid") or 0)
        port = int(payload.get("port") or 0)
        if pid <= 0 or port <= 0:
            return False
        if not self._pid_is_alive(pid):
            return False
        return self._probe_debug_endpoint(port) is not None

    def _session_state_matches_browser(
        self,
        payload: dict[str, Any],
        *,
        browser_state: dict[str, Any],
    ) -> bool:
        browser_managed = bool(browser_state.get("browser_managed"))
        payload_managed = bool(payload.get("browser_managed"))
        if browser_managed != payload_managed:
            return False
        if browser_managed:
            required_revision = str(browser_state.get("installed_revision") or "").strip()
            payload_revision = str(payload.get("browser_revision") or "").strip()
            return bool(required_revision) and payload_revision == required_revision
        if self.config.browser_executable_path is None:
            return True
        try:
            expected = str(
                Path(self.config.browser_executable_path).expanduser().resolve()
            )
        except Exception:
            return False
        return payload.get("browser_executable") == expected

    def _terminate_interactive_session(self, payload: dict[str, Any]) -> None:
        pid = int(payload.get("pid") or 0)
        if pid > 0 and self._pid_is_alive(pid):
            try:
                os.kill(pid, 15)
            except OSError:
                pass
            if not self._wait_for_pid_exit(pid, timeout_sec=5):
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
                self._wait_for_pid_exit(pid, timeout_sec=2)
        self._clear_session_state()

    def _revision_from_path(self, path: Path) -> str | None:
        match = re.search(r"chromium-(\d+)", str(path))
        return match.group(1) if match else None

    def _pid_is_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _launch_context(self, playwright, *, headless: bool):
        kwargs: dict[str, Any] = {
            "user_data_dir": str(self.config.browser_profile_dir),
            "headless": headless,
            "accept_downloads": True,
            "viewport": {"width": 1440, "height": 1080},
        }
        if self.config.browser_channel:
            kwargs["channel"] = self.config.browser_channel
        elif self.config.browser_executable_path is not None:
            kwargs["executable_path"] = str(self.config.browser_executable_path)
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
        selector_report["login_hints"] = self._collect_login_hints(page)
        selector_report["sign_in_ctas"] = self._collect_sign_in_ctas(page)
        selector_report["response_excerpt"] = self._collect_response_excerpt(page)
        selector_report["human_verification_page_url"] = selector_report["url"]
        selector_report["human_verification_page_title"] = selector_report["title"]
        selector_report["human_verification_signals"] = self._collect_human_verification_signals(
            page,
            response_excerpt=selector_report["response_excerpt"],
            page_title=selector_report["title"],
            page_url=selector_report["url"],
        )
        selector_report["human_verification_detected"] = bool(
            selector_report["human_verification_signals"]
        )
        selector_report["visible_controls"] = self._collect_interactive_controls(page)

        blocker = self._detect_page_blocker(page, selector_report)
        if blocker is not None:
            return blocker[0], selector_report

        if prompt_box is not None:
            return "ready", selector_report

        if "accounts.google.com" in page.url or selector_report["login_hints"]:
            return "needs_login", selector_report

        return "backend_blocker", selector_report

    def _state_message(self, state: str, selector_report: dict[str, Any]) -> str:
        response_excerpt = selector_report.get("response_excerpt", "")
        if state == "ready":
            if selector_report.get("interactive_handoff_performed"):
                return (
                    "Gemini browser backend is ready. The interactive login window was "
                    "closed and the dedicated profile is now running in the background."
                )
            if selector_report.get("auto_interactive_triggered"):
                return (
                    "Gemini browser backend is ready via the dedicated interactive session. "
                    f"Using profile {self.config.browser_profile_dir}."
                )
            return (
                "Gemini browser backend is ready. "
                f"Using profile {self.config.browser_profile_dir}."
            )
        if state == "needs_login":
            if selector_report.get("auto_interactive_triggered"):
                wait_seconds = selector_report.get("interactive_wait_seconds")
                return (
                    "Opened or reused the dedicated interactive Gemini browser window and "
                    f"waited {wait_seconds} seconds, but sign-in is still required."
                )
            if LOGIN_REQUIRED_TEXT_REGEX.search(response_excerpt):
                return "Gemini web app requires a signed-in session before it can create images."
            return "Gemini browser profile exists but sign-in is still required for image generation."
        if state == "needs_human_verification":
            if selector_report.get("auto_interactive_triggered"):
                wait_seconds = selector_report.get("interactive_wait_seconds")
                return (
                    "Opened or reused the dedicated interactive Gemini browser window and "
                    f"waited {wait_seconds} seconds, but manual human verification is still required."
                )
            return (
                "Gemini or Google requires manual human verification before image generation can continue."
            )
        if IMAGE_UNAVAILABLE_TEXT_REGEX.search(response_excerpt):
            return "Gemini web app reports image creation is unavailable for this account or location."
        if not selector_report.get("prompt_box_selector"):
            return "Gemini browser page loaded but the prompt box could not be confirmed."
        return "Gemini browser page did not expose a usable image-generation response."

    def _interactive_wait_message(
        self,
        status: str,
        wait_sec: int,
        *,
        timed_out: bool,
    ) -> str:
        if status == "needs_human_verification":
            if timed_out:
                return (
                    "Opened or reused the dedicated interactive Gemini browser window and "
                    f"waited {wait_sec} seconds, but manual human verification is still required. "
                    "The window remains open; complete the verification there and keep the current flow running."
                )
            return (
                "Opened or reused the dedicated interactive Gemini browser window because "
                "manual human verification is required before image generation can continue."
            )
        if timed_out:
            return (
                "Opened a dedicated interactive Gemini browser window and "
                f"waited {wait_sec} seconds, but sign-in is still required. "
                "The window remains open; finish login there and retry or keep "
                "the current flow running."
            )
        return (
            "Opened or reused the dedicated interactive Gemini browser window because "
            "sign-in is required before image generation can continue."
        )

    def _detect_page_blocker(
        self,
        page,
        selector_report: dict[str, Any],
    ) -> tuple[str, str] | None:
        response_excerpt = selector_report.get("response_excerpt") or self._collect_response_excerpt(page)
        selector_report["response_excerpt"] = response_excerpt
        human_verification_signals = selector_report.get("human_verification_signals")
        if human_verification_signals is None:
            human_verification_signals = self._collect_human_verification_signals(
                page,
                response_excerpt=response_excerpt,
                page_title=selector_report.get("title"),
                page_url=selector_report.get("url"),
            )
            selector_report["human_verification_signals"] = human_verification_signals
        selector_report["human_verification_detected"] = bool(human_verification_signals)
        selector_report["human_verification_page_url"] = selector_report.get("url") or page.url
        selector_report["human_verification_page_title"] = selector_report.get("title") or page.title()
        sign_in_ctas = selector_report.get("sign_in_ctas")
        if sign_in_ctas is None:
            sign_in_ctas = self._collect_sign_in_ctas(page)
            selector_report["sign_in_ctas"] = sign_in_ctas

        if human_verification_signals:
            return (
                "needs_human_verification",
                "Gemini or Google requires manual human verification "
                "(for example, 'I'm not a robot' or unusual traffic). "
                "Complete it in the dedicated interactive window and keep the current flow running.",
            )

        login_hints = selector_report.get("login_hints")
        if login_hints is None:
            login_hints = self._collect_login_hints(page)
            selector_report["login_hints"] = login_hints

        if "accounts.google.com" in page.url or login_hints or sign_in_ctas:
            return (
                "needs_login",
                "Gemini browser session is not signed in for image generation. "
                "Finish the dedicated-profile login flow and retry.",
            )

        if LOGIN_REQUIRED_TEXT_REGEX.search(response_excerpt):
            return (
                "needs_login",
                "Gemini web app asked for sign-in before it can create images.",
            )

        if IMAGE_UNAVAILABLE_TEXT_REGEX.search(response_excerpt):
            return (
                "backend_blocker",
                "Gemini web app reports image creation is unavailable for this account or location.",
            )

        return None

    def _collect_human_verification_signals(
        self,
        page,
        *,
        response_excerpt: str | None = None,
        page_title: str | None = None,
        page_url: str | None = None,
    ) -> list[str]:
        signals: list[str] = []
        url = page_url or page.url or ""
        title = page_title or page.title()
        excerpt = response_excerpt if response_excerpt is not None else self._collect_response_excerpt(page)

        if CAPTCHA_URL_REGEX.search(url):
            signals.append(f"url:{url[:200]}")
        if HUMAN_VERIFICATION_TEXT_REGEX.search(title):
            signals.append(f"title:{title[:200]}")
        text_match = HUMAN_VERIFICATION_TEXT_REGEX.search(excerpt)
        if text_match:
            signals.append(f"text:{text_match.group(0)}")

        try:
            dom_signals = page.evaluate(
                """() => {
                    const checks = [
                        ['iframe[src*="recaptcha"]', 'iframe:recaptcha'],
                        ['iframe[title*="recaptcha" i]', 'iframe:recaptcha-title'],
                        ['textarea[name="g-recaptcha-response"]', 'textarea:g-recaptcha-response'],
                        ['#recaptcha-anchor', 'checkbox:recaptcha-anchor'],
                        ['[class*="recaptcha"]', 'class:recaptcha'],
                        ['[id*="recaptcha"]', 'id:recaptcha'],
                        ['[aria-label*="robot" i]', 'aria:robot'],
                        ['[title*="robot" i]', 'title:robot'],
                        ['[aria-label*="human" i]', 'aria:human'],
                        ['form[action*="sorry"]', 'form:sorry'],
                    ];
                    const hits = [];
                    for (const [selector, label] of checks) {
                        if (document.querySelector(selector)) {
                            hits.push(label);
                        }
                    }
                    return hits;
                }"""
            )
        except Exception:
            dom_signals = []

        for signal in dom_signals:
            if signal and signal not in signals:
                signals.append(signal)
        return signals[:12]

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
            buttons = page.get_by_role("button", name=SIGN_IN_REGEX)
            if buttons.count() > 0 and buttons.first.is_visible():
                hints.append("button:sign-in")
        except Exception:
            pass
        try:
            links = page.get_by_role("link", name=SIGN_IN_REGEX)
            if links.count() > 0 and links.first.is_visible():
                hints.append("link:sign-in")
        except Exception:
            pass
        try:
            if page.get_by_text(SIGN_IN_REGEX).first.is_visible():
                hints.append("text:sign-in")
        except Exception:
            pass
        return hints

    def _collect_sign_in_ctas(self, page) -> list[str]:
        try:
            labels = page.evaluate(
                """(pattern) => {
                    const regex = new RegExp(pattern, "i");
                    const selectors = ['button', '[role="button"]', 'a', '[role="link"]'];
                    const labels = [];
                    const seen = new Set();
                    for (const selector of selectors) {
                        for (const el of document.querySelectorAll(selector)) {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width <= 0 || rect.height <= 0 || style.visibility === "hidden" || style.display === "none") {
                                continue;
                            }
                            const label = (el.getAttribute("aria-label") || el.innerText || el.textContent || "").trim().replace(/\\s+/g, " ");
                            if (!label || !regex.test(label) || seen.has(label)) {
                                continue;
                            }
                            seen.add(label);
                            labels.push(label);
                        }
                    }
                    return labels.slice(0, 10);
                }""",
                SIGN_IN_REGEX.pattern,
            )
        except Exception:
            return []
        return [label for label in labels if label]

    def _collect_interactive_controls(self, page) -> list[dict[str, str]]:
        try:
            controls = page.evaluate(
                """() => {
                    const selectors = ['button', '[role="button"]', '[role="menuitem"]', '[role="option"]', 'a', '[role="link"]'];
                    const items = [];
                    const seen = new Set();
                    for (const selector of selectors) {
                        for (const el of document.querySelectorAll(selector)) {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width <= 0 || rect.height <= 0 || style.visibility === "hidden" || style.display === "none") {
                                continue;
                            }
                            const aria = (el.getAttribute("aria-label") || "").trim();
                            const text = (el.innerText || el.textContent || "").trim().replace(/\\s+/g, " ");
                            const title = (el.getAttribute("title") || "").trim();
                            const label = aria || text || title;
                            if (!label) {
                                continue;
                            }
                            const role = (el.getAttribute("role") || "").trim();
                            const key = `${selector}|${role}|${label}`;
                            if (seen.has(key)) {
                                continue;
                            }
                            seen.add(key);
                            items.push({
                                selector,
                                role,
                                label,
                            });
                            if (items.length >= 80) {
                                return items;
                            }
                        }
                    }
                    return items;
                }"""
            )
        except Exception:
            return []
        return controls

    def _collect_response_excerpt(self, page, limit: int = 4000) -> str:
        try:
            text = page.evaluate(
                """(maxLen) => {
                    const source = document.querySelector("main") || document.body;
                    const raw = (source?.innerText || "").replace(/\\s+/g, " ").trim();
                    return raw.slice(0, maxLen);
                }""",
                limit,
            )
        except Exception:
            return ""
        return text or ""

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

    def _has_direct_image_entry(self, page) -> bool:
        return (
            self._find_visible_control_label(
                page,
                patterns=[IMAGE_MODE_REGEX],
                disallow=[
                    SIGN_IN_REGEX,
                    DOWNLOAD_BUTTON_REGEX,
                    IMAGE_TOOL_ACTIVE_REGEX,
                    NEW_CHAT_REGEX,
                    TEMPORARY_CHAT_REGEX,
                    TOOLS_BUTTON_REGEX,
                    MODE_PICKER_REGEX,
                ],
                selectors=("button", '[role="button"]'),
            )
            is not None
        )

    def _prepare_image_generation_mode(self, page, selector_report: dict[str, Any]) -> None:
        selector_report["controls_before_image_mode"] = self._collect_interactive_controls(page)
        selector_report["image_mode_status"] = "not_found"
        selector_report["image_tool_confirmed"] = False

        active_label = self._find_active_image_tool_label(page)
        if active_label:
            selector_report["image_mode_status"] = "already_selected"
            selector_report["image_mode_target"] = active_label
            selector_report["image_tool_confirmed"] = True
            return

        direct_label = self._click_visible_control(
            page,
            patterns=[IMAGE_MODE_REGEX],
            disallow=[
                SIGN_IN_REGEX,
                DOWNLOAD_BUTTON_REGEX,
                IMAGE_TOOL_ACTIVE_REGEX,
                NEW_CHAT_REGEX,
                TEMPORARY_CHAT_REGEX,
            ],
            selectors=("button", '[role="button"]'),
        )
        if direct_label:
            page.wait_for_timeout(700)
            active_label = self._find_active_image_tool_label(page)
            if active_label:
                selector_report["image_mode_status"] = "selected"
                selector_report["image_mode_source"] = "direct"
                selector_report["image_mode_target"] = active_label
                selector_report["image_tool_confirmed"] = True
                return

        attempts = [
            ("tools", page.get_by_role("button", name=TOOLS_BUTTON_REGEX)),
            ("mode_picker", page.get_by_role("button", name=MODE_PICKER_REGEX)),
        ]

        for attempt_name, trigger in attempts:
            if not self._click_first_visible(trigger):
                continue
            page.wait_for_timeout(700)
            selector_report[f"controls_after_{attempt_name}"] = self._collect_interactive_controls(page)
            selected_label = self._click_image_mode_target(page)
            if selected_label:
                page.wait_for_timeout(700)
                active_label = self._find_active_image_tool_label(page)
                if active_label:
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(250)
                    except Exception:
                        pass
                    selector_report["image_mode_status"] = "selected"
                    selector_report["image_mode_source"] = attempt_name
                    selector_report["image_mode_target"] = active_label
                    selector_report["image_tool_confirmed"] = True
                    return
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

        raise BrowserStateError(
            "backend_blocker",
            "Could not activate Gemini's image-generation tool before rendering.",
        )

    def _prepare_model_mode(self, page, selector_report: dict[str, Any]) -> None:
        selector_report["model_mode_requested"] = "thinking"
        selector_report["model_mode_selected"] = None
        selector_report["model_mode_fallback"] = False
        selector_report["model_mode_fallback_reason"] = None
        selector_report["controls_before_mode_selection"] = self._collect_interactive_controls(
            page
        )
        selector_report["prompt_surface_text"] = self._collect_prompt_surface_text(page)

        if self.config.normalized_browser_mode_policy == "prefer_fast":
            confirmed = self._ensure_model_mode(
                page,
                selector_report=selector_report,
                patterns=[FAST_MODE_REGEX],
                fallback_reason=None,
            )
            if confirmed is None:
                raise BrowserStateError(
                    "backend_blocker",
                    "Could not confirm Gemini's Fast/Flash mode before rendering.",
                )
            selector_report["model_mode_selected"] = confirmed
            return

        confirmed = self._ensure_model_mode(
            page,
            selector_report=selector_report,
            patterns=[THINKING_MODE_REGEX],
            fallback_reason=None,
        )
        if confirmed is not None:
            selector_report["model_mode_selected"] = confirmed
            return

        selector_report["model_mode_fallback"] = True
        selector_report["model_mode_fallback_reason"] = (
            "Gemini did not expose a confirmed Thinking/Pro mode in the current session."
        )
        confirmed = self._ensure_model_mode(
            page,
            selector_report=selector_report,
            patterns=[FAST_MODE_REGEX],
            fallback_reason=selector_report["model_mode_fallback_reason"],
        )
        if confirmed is None:
            raise BrowserStateError(
                "backend_blocker",
                "Could not confirm Gemini's mode selection before rendering. "
                "Thinking/Pro was unavailable and Fast/Flash could not be confirmed.",
            )
        selector_report["model_mode_selected"] = confirmed

    def _ensure_model_mode(
        self,
        page,
        *,
        selector_report: dict[str, Any],
        patterns: list[re.Pattern[str]],
        fallback_reason: str | None,
    ) -> str | None:
        confirmed = self._confirm_model_mode(
            page,
            patterns=patterns,
            selector_report=selector_report,
        )
        if confirmed is not None:
            if fallback_reason:
                selector_report["model_mode_fallback_reason"] = fallback_reason
            return confirmed

        if not self._open_mode_picker(page, selector_report):
            return None
        selector_report["mode_controls_after_picker"] = self._collect_mode_controls(page)
        clicked = self._click_mode_target(
            page,
            patterns=patterns,
            disallow=[MODE_PICKER_OPEN_REGEX],
        )
        if clicked is None:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return None
        selector_report["mode_target_clicked"] = clicked
        page.wait_for_timeout(700)
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception:
            pass
        confirmed = self._confirm_model_mode(
            page,
            patterns=patterns,
            selector_report=selector_report,
        )
        if confirmed is not None and fallback_reason:
            selector_report["model_mode_fallback_reason"] = fallback_reason
        return confirmed

    def _open_mode_picker(self, page, selector_report: dict[str, Any]) -> bool:
        label = self._click_visible_control(
            page,
            patterns=[MODE_PICKER_REGEX],
            disallow=[
                SIGN_IN_REGEX,
                DOWNLOAD_BUTTON_REGEX,
                IMAGE_TOOL_ACTIVE_REGEX,
                TEMPORARY_CHAT_REGEX,
                NEW_CHAT_REGEX,
            ],
            selectors=("button", '[role="button"]'),
        )
        if label:
            selector_report["mode_picker_trigger"] = label
            page.wait_for_timeout(500)
            return True
        selector_report["mode_picker_controls_before_failure"] = self._collect_interactive_controls(
            page
        )
        return False

    def _confirm_model_mode(
        self,
        page,
        *,
        patterns: list[re.Pattern[str]],
        selector_report: dict[str, Any] | None = None,
    ) -> str | None:
        controls = self._collect_mode_controls(page)
        if selector_report is not None:
            selector_report["mode_controls_visible"] = controls
        for control in controls:
            label = control.get("label", "")
            if not any(pattern.search(label) for pattern in patterns):
                continue
            if self._control_looks_active(control):
                return label
        for control in controls:
            label = control.get("label", "")
            if not any(pattern.search(label) for pattern in patterns):
                continue
            if control.get("role") in {"button", "tab"}:
                return label
        if len(controls) == 1:
            label = controls[0].get("label", "")
            if any(pattern.search(label) for pattern in patterns):
                return label
        prompt_surface_text = self._collect_prompt_surface_text(page)
        if selector_report is not None:
            selector_report["prompt_surface_text"] = prompt_surface_text
        for pattern in patterns:
            match = pattern.search(prompt_surface_text)
            if match:
                return match.group(0)
        response_excerpt = self._collect_response_excerpt(page, limit=600)
        if selector_report is not None:
            selector_report["mode_response_excerpt"] = response_excerpt
        for pattern in patterns:
            match = pattern.search(response_excerpt)
            if match:
                return match.group(0)
        return None

    def _collect_prompt_surface_text(self, page) -> str:
        located = self._find_prompt_box(page)
        if located is None:
            return ""
        _, prompt_box = located
        try:
            text = prompt_box.evaluate(
                """(el) => {
                    let node = el;
                    for (let depth = 0; depth < 6 && node; depth += 1, node = node.parentElement) {
                        const text = (node.innerText || "").replace(/\\s+/g, " ").trim();
                        if (text.length >= 8) {
                            return text.slice(0, 600);
                        }
                    }
                    return "";
                }"""
            )
        except Exception:
            return ""
        return text or ""

    def _collect_mode_controls(self, page) -> list[dict[str, str]]:
        try:
            controls = page.evaluate(
                """() => {
                    const selectors = [
                        ['[role="menuitemradio"]', 'menuitemradio'],
                        ['[role="menuitem"]', 'menuitem'],
                        ['[role="option"]', 'option'],
                        ['[role="radio"]', 'radio'],
                        ['button', 'button'],
                        ['[role="button"]', 'button'],
                        ['[role="tab"]', 'tab'],
                    ];
                    const items = [];
                    const seen = new Set();
                    for (const [selector, fallbackRole] of selectors) {
                        for (const el of document.querySelectorAll(selector)) {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width <= 0 || rect.height <= 0 || style.visibility === "hidden" || style.display === "none") {
                                continue;
                            }
                            const label = (el.getAttribute("aria-label") || el.innerText || el.textContent || el.getAttribute("title") || "")
                                .trim()
                                .replace(/\\s+/g, " ");
                            if (!label) {
                                continue;
                            }
                            const role = (el.getAttribute("role") || fallbackRole || "").trim() || fallbackRole;
                            const key = `${selector}|${role}|${label}`;
                            if (seen.has(key)) {
                                continue;
                            }
                            seen.add(key);
                            items.push({
                                label,
                                role,
                                aria_pressed: (el.getAttribute("aria-pressed") || "").trim(),
                                aria_selected: (el.getAttribute("aria-selected") || "").trim(),
                                aria_checked: (el.getAttribute("aria-checked") || "").trim(),
                                data_state: (el.getAttribute("data-state") || "").trim(),
                            });
                            if (items.length >= 60) {
                                return items;
                            }
                        }
                    }
                    return items;
                }"""
            )
        except Exception:
            return []
        filtered: list[dict[str, str]] = []
        for control in controls:
            label = str(control.get("label", "")).strip()
            if not label:
                continue
            if SIGN_IN_REGEX.search(label) or DOWNLOAD_BUTTON_REGEX.search(label):
                continue
            filtered.append(
                {
                    "label": label,
                    "role": str(control.get("role", "")).strip(),
                    "aria_pressed": str(control.get("aria_pressed", "")).strip(),
                    "aria_selected": str(control.get("aria_selected", "")).strip(),
                    "aria_checked": str(control.get("aria_checked", "")).strip(),
                    "data_state": str(control.get("data_state", "")).strip(),
                }
            )
        return filtered

    def _control_looks_active(self, control: dict[str, str]) -> bool:
        for key in ("aria_pressed", "aria_selected", "aria_checked", "data_state"):
            value = (control.get(key) or "").strip().lower()
            if value in ACTIVE_CONTROL_STATE_VALUES:
                return True
        return False

    def _click_mode_target(
        self,
        page,
        *,
        patterns: list[re.Pattern[str]],
        disallow: list[re.Pattern[str]] | None = None,
    ) -> str | None:
        try:
            label = page.evaluate(
                """({patterns, disallow}) => {
                    const allow = patterns.map((pattern) => new RegExp(pattern, "i"));
                    const reject = (disallow || []).map((pattern) => new RegExp(pattern, "i"));
                    const selectors = [
                        ['[role="menuitemradio"]', 'menuitemradio'],
                        ['[role="option"]', 'option'],
                        ['[role="menuitem"]', 'menuitem'],
                        ['[role="radio"]', 'radio'],
                        ['button', 'button'],
                        ['[role="button"]', 'button'],
                    ];
                    for (const [selector] of selectors) {
                        for (const el of document.querySelectorAll(selector)) {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width <= 0 || rect.height <= 0 || style.visibility === "hidden" || style.display === "none") {
                                continue;
                            }
                            const label = (el.getAttribute("aria-label") || el.innerText || el.textContent || el.getAttribute("title") || "")
                                .trim()
                                .replace(/\\s+/g, " ");
                            if (!label) {
                                continue;
                            }
                            if (!allow.some((regex) => regex.test(label))) {
                                continue;
                            }
                            if (reject.some((regex) => regex.test(label))) {
                                continue;
                            }
                            el.click();
                            return label;
                        }
                    }
                    return null;
                }""",
                {
                    "patterns": [pattern.pattern for pattern in patterns],
                    "disallow": [pattern.pattern for pattern in (disallow or [])],
                },
            )
        except Exception:
            return None
        return label if isinstance(label, str) and label else None

    def _click_image_mode_target(self, page) -> str | None:
        locators = [
            page.get_by_role("button", name=IMAGE_MODE_REGEX),
            page.get_by_role("menuitem", name=IMAGE_MODE_REGEX),
            page.get_by_role("option", name=IMAGE_MODE_REGEX),
            page.get_by_text(IMAGE_MODE_REGEX),
        ]
        for locator in locators:
            try:
                count = min(locator.count(), 8)
            except Exception:
                continue
            for idx in range(count):
                candidate = locator.nth(idx)
                try:
                    if not candidate.is_visible():
                        continue
                    label = (
                        candidate.get_attribute("aria-label")
                        or candidate.get_attribute("title")
                        or candidate.inner_text()
                        or ""
                    ).strip()
                    if not label:
                        continue
                    if SIGN_IN_REGEX.search(label) or DOWNLOAD_BUTTON_REGEX.search(label):
                        continue
                    if label.lower() in {"send", "send message", "fast"}:
                        continue
                    candidate.click()
                    return label
                except Exception:
                    continue
        return None

    def _click_first_visible(self, locator) -> bool:
        try:
            count = min(locator.count(), 5)
        except Exception:
            return False
        for idx in range(count):
            candidate = locator.nth(idx)
            try:
                if candidate.is_visible() and candidate.is_enabled():
                    candidate.click()
                    return True
            except Exception:
                continue
        return False

    def _find_visible_control_label(
        self,
        page,
        *,
        patterns: list[re.Pattern[str]],
        disallow: list[re.Pattern[str]] | None = None,
        selectors: tuple[str, ...] = ("button", '[role="button"]', "a", '[role="link"]'),
    ) -> str | None:
        try:
            label = page.evaluate(
                """({patterns, disallow, selectors}) => {
                    const allow = patterns.map((pattern) => new RegExp(pattern, "i"));
                    const reject = (disallow || []).map((pattern) => new RegExp(pattern, "i"));
                    for (const selector of selectors) {
                        for (const el of document.querySelectorAll(selector)) {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width <= 0 || rect.height <= 0 || style.visibility === "hidden" || style.display === "none") {
                                continue;
                            }
                            const label = (el.getAttribute("aria-label") || el.innerText || el.textContent || el.getAttribute("title") || "")
                                .trim()
                                .replace(/\\s+/g, " ");
                            if (!label) {
                                continue;
                            }
                            if (!allow.some((regex) => regex.test(label))) {
                                continue;
                            }
                            if (reject.some((regex) => regex.test(label))) {
                                continue;
                            }
                            return label;
                        }
                    }
                    return null;
                }""",
                {
                    "patterns": [pattern.pattern for pattern in patterns],
                    "disallow": [pattern.pattern for pattern in (disallow or [])],
                    "selectors": list(selectors),
                },
            )
        except Exception:
            return None
        return label if isinstance(label, str) and label else None

    def _click_visible_control(
        self,
        page,
        *,
        patterns: list[re.Pattern[str]],
        disallow: list[re.Pattern[str]] | None = None,
        selectors: tuple[str, ...] = ("button", '[role="button"]', "a", '[role="link"]'),
    ) -> str | None:
        try:
            label = page.evaluate(
                """({patterns, disallow, selectors}) => {
                    const allow = patterns.map((pattern) => new RegExp(pattern, "i"));
                    const reject = (disallow || []).map((pattern) => new RegExp(pattern, "i"));
                    for (const selector of selectors) {
                        for (const el of document.querySelectorAll(selector)) {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width <= 0 || rect.height <= 0 || style.visibility === "hidden" || style.display === "none") {
                                continue;
                            }
                            const label = (el.getAttribute("aria-label") || el.innerText || el.textContent || el.getAttribute("title") || "")
                                .trim()
                                .replace(/\\s+/g, " ");
                            if (!label) {
                                continue;
                            }
                            if (!allow.some((regex) => regex.test(label))) {
                                continue;
                            }
                            if (reject.some((regex) => regex.test(label))) {
                                continue;
                            }
                            el.click();
                            return label;
                        }
                    }
                    return null;
                }""",
                {
                    "patterns": [pattern.pattern for pattern in patterns],
                    "disallow": [pattern.pattern for pattern in (disallow or [])],
                    "selectors": list(selectors),
                },
            )
        except Exception:
            return None
        return label if isinstance(label, str) and label else None

    def _clear_prompt_box(self, prompt_box) -> None:
        self._focus_prompt_box(prompt_box)
        try:
            prompt_box.fill("")
            return
        except Exception:
            pass
        prompt_box.evaluate(
            """(el) => {
                el.focus();
                if ("value" in el) {
                    el.value = "";
                } else {
                    el.textContent = "";
                }
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
            }"""
        )

    def _focus_prompt_box(self, prompt_box) -> None:
        try:
            prompt_box.evaluate(
                """(el) => {
                    if (typeof el.focus === "function") {
                        el.focus();
                    }
                }"""
            )
        except Exception:
            pass

    def _prompt_box_is_empty(self, prompt_box) -> bool:
        try:
            return bool(
                prompt_box.evaluate(
                    """(el) => {
                        if ("value" in el) {
                            return !String(el.value || "").trim();
                        }
                        return !String(el.textContent || "").trim();
                    }"""
                )
            )
        except Exception:
            return False

    def _reset_render_session(
        self,
        page,
        selector_report: dict[str, Any],
        *,
        session_mode_override: str | None = None,
    ) -> None:
        requested_mode = session_mode_override or self.config.normalized_render_session_mode
        selector_report["render_session_mode_requested"] = self.config.normalized_render_session_mode
        if session_mode_override:
            selector_report["render_session_mode_override"] = session_mode_override
        selector_report["render_reset_url_before"] = page.url

        if requested_mode != "reuse":
            self._navigate_to_app(page)

        actual_mode = "reuse"
        if requested_mode == "temporary":
            clicked = self._click_visible_control(
                page,
                patterns=[TEMPORARY_CHAT_REGEX],
                disallow=[SIGN_IN_REGEX],
            )
            if clicked:
                actual_mode = "temporary"
                page.wait_for_timeout(1200)
                if not self._has_direct_image_entry(page):
                    clicked = self._click_visible_control(
                        page,
                        patterns=[NEW_CHAT_REGEX],
                        disallow=[SIGN_IN_REGEX],
                    )
                    if clicked:
                        selector_report["render_session_mode_fallback_reason"] = (
                            "Temporary chat did not expose Gemini's direct image entry."
                        )
                        actual_mode = "new_chat"
            else:
                clicked = self._click_visible_control(
                    page,
                    patterns=[NEW_CHAT_REGEX],
                    disallow=[SIGN_IN_REGEX],
                )
                if not clicked:
                    if self._page_is_clean_home_surface(page):
                        actual_mode = "home_surface"
                        selector_report["render_session_mode_fallback_reason"] = (
                            "Gemini was already on a clean home surface without a separate "
                            "temporary/new-chat control."
                        )
                    else:
                        raise BrowserStateError(
                            "backend_blocker",
                            "Could not reset Gemini to a temporary or new chat before rendering.",
                        )
                else:
                    actual_mode = "new_chat"
        elif requested_mode == "new_chat":
            clicked = self._click_visible_control(
                page,
                patterns=[NEW_CHAT_REGEX],
                disallow=[SIGN_IN_REGEX],
            )
            if not clicked:
                if self._page_is_clean_home_surface(page):
                    actual_mode = "home_surface"
                else:
                    raise BrowserStateError(
                        "backend_blocker",
                        "Could not open a new Gemini chat before rendering.",
                    )
            else:
                actual_mode = "new_chat"

        page.wait_for_timeout(1200)
        located = self._find_prompt_box(page)
        if located is None:
            raise BrowserStateError(
                "backend_blocker",
                "Could not locate the Gemini prompt box after resetting the chat session.",
            )
        prompt_selector, prompt_box = located
        self._clear_prompt_box(prompt_box)
        if not self._prompt_box_is_empty(prompt_box):
            raise BrowserStateError(
                "backend_blocker",
                "Gemini prompt box was not empty after resetting the chat session.",
            )

        selector_report["session_reset_mode"] = actual_mode
        selector_report["render_reset_url_after"] = page.url
        selector_report["prompt_box_selector"] = prompt_selector
        selector_report["image_tool_confirmed"] = False
        selector_report["post_reset_download_candidates"] = self._collect_download_candidates(page)
        selector_report["post_reset_visual_candidates"] = self._collect_visual_candidates(page)

    def _page_is_clean_home_surface(self, page) -> bool:
        located = self._find_prompt_box(page)
        if located is None:
            return False
        if self._collect_visual_candidates(page) or self._collect_download_candidates(page):
            return False
        excerpt = self._collect_response_excerpt(page, limit=600)
        if HOME_SURFACE_REGEX.search(excerpt):
            return True
        if "gemini.google.com/app" in (page.url or "") and self._has_direct_image_entry(page):
            return True
        return False

    def _find_active_image_tool_label(self, page) -> str | None:
        return self._find_visible_control_label(
            page,
            patterns=[IMAGE_TOOL_ACTIVE_REGEX],
            selectors=("button", '[role="button"]'),
        )

    def _detect_context_contamination(
        self,
        *,
        selector_report: dict[str, Any],
        baseline_visual: list[dict[str, Any]],
        baseline_downloads: list[dict[str, Any]],
    ) -> str | None:
        if selector_report.get("session_reset_mode") != "reuse":
            if baseline_visual or baseline_downloads:
                return (
                    "Gemini still showed pre-existing image artifacts after the chat "
                    "session reset, so the render context is not clean."
                )
        submit_control = selector_report.get("submit_control", "")
        if submit_control and submit_control != "keyboard:Enter" and not TRUSTED_SUBMIT_REGEX.search(submit_control):
            return (
                "Gemini prompt submission used an unexpected control "
                f"({submit_control}), which suggests the page stayed in a prior conversation."
            )
        return None

    def _submit_prompt(self, page, prompt: str, selector_report: dict[str, Any]) -> None:
        located = self._find_prompt_box(page)
        if located is None:
            raise BrowserStateError(
                "backend_blocker",
                "Could not locate the Gemini prompt box.",
            )
        prompt_selector, prompt_box = located
        selector_report["prompt_box_selector"] = prompt_selector
        self._clear_prompt_box(prompt_box)
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
        self._focus_prompt_box(prompt_box)
        page.wait_for_timeout(400)

        trusted_submit_locators = [
            page.get_by_role("button", name="发送", exact=True),
            page.locator('button[aria-label*="发送"]'),
            page.get_by_role("button", name="Send", exact=True),
            page.locator('button[aria-label*="Send" i]'),
            page.get_by_role("button", name=TRUSTED_SUBMIT_REGEX),
            page.locator('button[type="submit"]'),
        ]
        deadline = time.time() + 4.0
        while time.time() < deadline:
            for locator in trusted_submit_locators:
                try:
                    count = min(locator.count(), 5)
                except Exception:
                    continue
                for idx in range(count):
                    button = locator.nth(idx)
                    try:
                        if not button.is_visible() or not button.is_enabled():
                            continue
                        label = (
                            button.get_attribute("aria-label")
                            or button.get_attribute("title")
                            or button.inner_text()
                            or "submit"
                        ).strip()
                        if label and not TRUSTED_SUBMIT_REGEX.search(label) and locator != trusted_submit_locators[-1]:
                            continue
                        button.click()
                        selector_report["submit_control"] = label or "submit"
                        return
                    except Exception:
                        continue
            page.wait_for_timeout(250)

        selector_report["submit_controls_before_failure"] = self._collect_interactive_controls(page)
        raise BrowserStateError(
            "backend_blocker",
            "Could not confirm Gemini's explicit send button after filling the prompt.",
        )

    def _wait_for_generated_artifact(
        self,
        *,
        page,
        baseline_visual: list[dict[str, Any]],
        baseline_downloads: list[dict[str, Any]],
        timeout_sec: int,
        selector_report: dict[str, Any],
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        baseline_visual_signatures = {item["signature"] for item in baseline_visual}
        baseline_download_signatures = {item["signature"] for item in baseline_downloads}

        while time.time() < deadline:
            state, state_report = self._detect_state(page)
            selector_report["state_during_wait"] = state_report
            blocker = self._detect_page_blocker(page, state_report)
            if blocker is not None:
                raise BrowserStateError(*blocker)
            if state == "backend_blocker" and not state_report.get("prompt_box_selector"):
                raise BrowserStateError(
                    "backend_blocker",
                    "Gemini browser page lost the prompt box before an image was generated.",
                )

            download_candidates = self._collect_download_candidates(page)
            selector_report["download_candidates"] = download_candidates
            for candidate in download_candidates:
                if candidate["signature"] not in baseline_download_signatures:
                    return candidate

            visual_candidates = self._collect_visual_candidates(page)
            selector_report["visual_candidates"] = visual_candidates
            for candidate in visual_candidates:
                if candidate["signature"] not in baseline_visual_signatures:
                    return candidate

            page.wait_for_timeout(1500)

        raise BrowserStateError(
            "backend_blocker",
            "Timed out waiting for Gemini to generate an image.",
        )

    def _collect_visual_candidates(self, page) -> list[dict[str, Any]]:
        payload = page.evaluate(
            """() => {
                const selectors = [
                    ["main img", "img"],
                    ["img[src^='blob:']", "img"],
                    ["img[src^='data:']", "img"],
                    ["main canvas", "canvas"],
                ];
                const items = [];
                for (const [selector, kind] of selectors) {
                    const nodes = Array.from(document.querySelectorAll(selector));
                    nodes.forEach((el, index) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        const src = kind === "img" ? (el.currentSrc || el.src || "") : "";
                        const visible = rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
                        if (!visible || rect.width < 256 || rect.height < 256) {
                            return;
                        }
                        items.push({
                            kind,
                            selector,
                            dom_index: index,
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            src,
                        });
                    });
                }
                return items;
            }"""
        )
        candidates = []
        seen: set[str] = set()
        for item in payload:
            signature = (
                f"{item['kind']}:{item['selector']}:{item['dom_index']}:"
                f"{item.get('src', '')[:120]}:{item['width']}x{item['height']}"
            )
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append({**item, "signature": signature})
        return candidates

    def _collect_download_candidates(self, page) -> list[dict[str, Any]]:
        try:
            payload = page.evaluate(
                """(pattern) => {
                    const regex = new RegExp(pattern, "i");
                    return Array.from(document.querySelectorAll("button, [role='button'], a"))
                        .map((el, index) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            const label = (el.getAttribute("aria-label") || el.innerText || el.textContent || el.getAttribute("title") || "")
                                .trim()
                                .replace(/\\s+/g, " ");
                            return {
                                index,
                                label,
                                visible: rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none",
                            };
                        })
                        .filter((item) => item.visible && item.label && regex.test(item.label))
                        .slice(0, 10);
                }""",
                DOWNLOAD_BUTTON_REGEX.pattern,
            )
        except Exception:
            return []

        candidates = []
        for item in payload:
            signature = f"download:{item['index']}:{item['label']}"
            candidates.append(
                {
                    "kind": "download_button",
                    "dom_index": item["index"],
                    "label": item["label"],
                    "signature": signature,
                }
            )
        return candidates

    def _save_artifact(self, *, page, artifact: dict[str, Any], output_path: Path) -> str:
        if artifact["kind"] == "download_button":
            if self._save_download_candidate(page, artifact, output_path):
                return "download_button"
            raise RuntimeError("A Gemini download control appeared but the file could not be saved.")

        if self._try_download_button(page, output_path):
            return "download_button"

        if artifact["kind"] == "img":
            selector = artifact.get("selector", "main img")
            locator = page.locator(selector).nth(int(artifact["dom_index"]))
            src = locator.get_attribute("src") or ""
            if src:
                try:
                    self._write_image_source(page, src, output_path)
                    return "image_source"
                except Exception:
                    locator.screenshot(path=str(output_path), type="png")
                    return "element_screenshot"

        if artifact["kind"] == "canvas":
            selector = artifact.get("selector", "main canvas")
            page.locator(selector).nth(int(artifact["dom_index"])).screenshot(
                path=str(output_path),
                type="png",
            )
            return "canvas_screenshot"

        raise RuntimeError("No supported Gemini image artifact could be saved.")

    def _save_download_candidate(self, page, artifact: dict[str, Any], output_path: Path) -> bool:
        label = artifact.get("label", "")
        try:
            buttons = page.get_by_role("button", name=DOWNLOAD_BUTTON_REGEX)
            count = min(buttons.count(), 8)
        except Exception:
            return False
        for idx in range(count):
            button = buttons.nth(idx)
            try:
                current_label = (
                    button.get_attribute("aria-label")
                    or button.get_attribute("title")
                    or button.inner_text()
                    or ""
                ).strip()
                if label and current_label and label != current_label:
                    continue
                with page.expect_download(timeout=5000) as download_info:
                    button.click()
                download = download_info.value
                download.save_as(str(output_path))
                return True
            except Exception:
                continue
        return self._try_download_button(page, output_path)

    def _try_download_button(self, page, output_path: Path) -> bool:
        try:
            buttons = page.get_by_role("button", name=DOWNLOAD_BUTTON_REGEX)
            count = min(buttons.count(), 8)
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

    def _close_page_session(self, session: BrowserPageSession | None) -> None:
        if session is None:
            return
        if session.mode == "persistent" and session.context is not None:
            try:
                session.context.close()
            except Exception:
                pass

    def _stop_playwright(self, playwright) -> None:
        if playwright is None:
            return
        try:
            playwright.stop()
        except Exception:
            pass
