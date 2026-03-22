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
    browser_timeout_sec: int = field(
        default_factory=lambda: int(os.getenv("GEMINI_BROWSER_TIMEOUT_SEC", "240"))
    )
    browser_app_url: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BROWSER_APP_URL",
            "https://gemini.google.com/app",
        )
    )
    browser_channel: str = field(
        default_factory=lambda: os.getenv("GEMINI_BROWSER_CHANNEL", "")
    )
    browser_debug_dir: Path | None = None

    def __post_init__(self) -> None:
        self.work_dir = Path(self.work_dir)
        self.output_dir = Path(self.output_dir)
        if self.reference_dir is not None:
            self.reference_dir = Path(self.reference_dir)
        self.browser_profile_dir = Path(self.browser_profile_dir)
        if self.browser_debug_dir is None:
            self.browser_debug_dir = (
                self.work_dir / "refine-logs" / "gemini-browser-debug"
            )
        else:
            self.browser_debug_dir = Path(self.browser_debug_dir)

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


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}
