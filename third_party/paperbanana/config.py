# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived from dwzhu-pku/PaperBanana and modified for ARIS runtime use.

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IllustrationConfig:
    """Runtime configuration for the trimmed PaperBanana illustration pipeline."""

    work_dir: Path
    output_dir: Path
    reference_dir: Path | None = None
    backend: str = field(
        default_factory=lambda: os.getenv(
            "ILLUSTRATION_BACKEND",
            "browser",
        )
    )
    api_base: str = field(
        default_factory=lambda: os.getenv(
            "PAPER_ILLUSTRATION_API_BASE",
            "https://generativelanguage.googleapis.com/v1beta",
        )
    )
    api_key_env: str = field(
        default_factory=lambda: os.getenv(
            "PAPER_ILLUSTRATION_API_KEY_ENV",
            "PAPER_ILLUSTRATION_API_KEY",
        )
    )
    text_model_name: str = field(
        default_factory=lambda: os.getenv(
            "PAPER_ILLUSTRATION_TEXT_MODEL",
            "gemini-2.5-pro",
        )
    )
    image_model_name: str = field(
        default_factory=lambda: os.getenv(
            "PAPER_ILLUSTRATION_IMAGE_MODEL",
            "gemini-2.5-flash-image-preview",
        )
    )
    temperature: float = 0.4
    max_critic_rounds: int = 3
    target_score: int = 9
    retrieval_setting: str = "auto"
    request_timeout: int = 240
    browser_profile_mode: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BROWSER_PROFILE_MODE",
            "dedicated",
        )
    )
    browser_profile_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "GEMINI_BROWSER_PROFILE_DIR",
                str(Path.home() / ".claude" / "state" / "gemini-browser" / "profile"),
            )
        )
    )
    browser_headless: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("GEMINI_BROWSER_HEADLESS", "false")
        )
    )
    browser_auto_interactive: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("GEMINI_BROWSER_AUTO_INTERACTIVE", "true")
        )
    )
    browser_auto_interactive_wait_sec: int = field(
        default_factory=lambda: int(
            os.getenv("GEMINI_BROWSER_AUTO_INTERACTIVE_WAIT_SEC", "300")
        )
    )
    browser_auto_wait_for_human_verification: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("GEMINI_BROWSER_AUTO_WAIT_FOR_HUMAN_VERIFICATION", "true")
        )
    )
    browser_auto_update: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("GEMINI_BROWSER_AUTO_UPDATE", "true")
        )
    )
    browser_update_scope: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BROWSER_UPDATE_SCOPE",
            "playwright_chromium",
        )
    )
    browser_close_interactive_after_ready: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("GEMINI_BROWSER_CLOSE_INTERACTIVE_AFTER_READY", "true")
        )
    )
    browser_render_session_mode: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BROWSER_RENDER_SESSION_MODE",
            "temporary",
        )
    )
    browser_retry_on_context_leak: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("GEMINI_BROWSER_RENDER_RETRY_ON_CONTEXT_LEAK", "true")
        )
    )
    browser_render_max_retries: int = field(
        default_factory=lambda: int(
            os.getenv("GEMINI_BROWSER_RENDER_MAX_RETRIES", "2")
        )
    )
    browser_timeout_sec: int = field(
        default_factory=lambda: int(os.getenv("GEMINI_BROWSER_TIMEOUT_SEC", "240"))
    )
    browser_prune_extra_pages: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("GEMINI_BROWSER_PRUNE_EXTRA_PAGES", "true")
        )
    )
    browser_max_interactive_pages: int = field(
        default_factory=lambda: int(
            os.getenv("GEMINI_BROWSER_MAX_INTERACTIVE_PAGES", "1")
        )
    )
    browser_remote_debug_port: int = field(
        default_factory=lambda: int(os.getenv("GEMINI_BROWSER_REMOTE_DEBUG_PORT", "9223"))
    )
    browser_app_url: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BROWSER_APP_URL",
            "https://gemini.google.com/app",
        )
    )
    browser_executable_path: Path | None = field(
        default_factory=lambda: Path(raw).expanduser()
        if (raw := os.getenv("GEMINI_BROWSER_EXECUTABLE_PATH", "").strip())
        else None
    )
    browser_channel: str = field(
        default_factory=lambda: os.getenv("GEMINI_BROWSER_CHANNEL", "")
    )
    browser_mode_policy: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BROWSER_MODE_POLICY",
            "prefer_thinking_fallback_fast",
        )
    )
    browser_debug_dir: Path | None = None
    browser_session_state_path: Path | None = None
    browser_launch_log_path: Path | None = None

    def __post_init__(self) -> None:
        self.work_dir = Path(self.work_dir)
        self.output_dir = Path(self.output_dir)
        if self.reference_dir is not None:
            self.reference_dir = Path(self.reference_dir)
        self.browser_profile_dir = Path(self.browser_profile_dir)
        if self.browser_executable_path is not None:
            self.browser_executable_path = Path(self.browser_executable_path)
        if self.browser_debug_dir is None:
            self.browser_debug_dir = (
                self.work_dir / "refine-logs" / "gemini-browser-debug"
            )
        else:
            self.browser_debug_dir = Path(self.browser_debug_dir)
        state_dir = self.browser_profile_dir.parent
        if self.browser_session_state_path is None:
            self.browser_session_state_path = state_dir / "session.json"
        else:
            self.browser_session_state_path = Path(self.browser_session_state_path)
        if self.browser_launch_log_path is None:
            self.browser_launch_log_path = state_dir / "interactive-browser.log"
        else:
            self.browser_launch_log_path = Path(self.browser_launch_log_path)

    def resolve_api_key(self) -> str:
        candidates = [
            self.api_key_env,
            "PAPER_ILLUSTRATION_API_KEY",
            "GEMINI_API_KEY",
        ]
        for env_name in candidates:
            value = os.getenv(env_name)
            if value:
                return value
        return ""

    @property
    def has_backend_credentials(self) -> bool:
        return bool(self.resolve_api_key())

    @property
    def normalized_backend(self) -> str:
        backend = (self.backend or "browser").strip().lower()
        return backend if backend in {"browser", "api"} else "browser"

    @property
    def uses_browser_backend(self) -> bool:
        return self.normalized_backend == "browser"

    @property
    def uses_api_backend(self) -> bool:
        return self.normalized_backend == "api"

    @property
    def normalized_render_session_mode(self) -> str:
        mode = (self.browser_render_session_mode or "temporary").strip().lower()
        return mode if mode in {"temporary", "new_chat", "reuse"} else "temporary"

    @property
    def normalized_browser_update_scope(self) -> str:
        scope = (self.browser_update_scope or "playwright_chromium").strip().lower()
        return scope if scope == "playwright_chromium" else "playwright_chromium"

    @property
    def normalized_browser_mode_policy(self) -> str:
        policy = (self.browser_mode_policy or "").strip().lower()
        if policy == "prefer_fast":
            return "prefer_fast"
        return "prefer_thinking_fallback_fast"

    @property
    def normalized_browser_max_interactive_pages(self) -> int:
        return max(int(self.browser_max_interactive_pages or 1), 1)


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}
