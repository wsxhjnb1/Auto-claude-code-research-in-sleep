# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived from dwzhu-pku/PaperBanana and modified for ARIS runtime use.

from __future__ import annotations

from abc import ABC, abstractmethod

from .config import IllustrationConfig


class BaseAgent(ABC):
    """Small shared base for the trimmed PaperBanana agents."""

    def __init__(self, config: IllustrationConfig) -> None:
        self.config = config

    @abstractmethod
    def process(self, *args, **kwargs):
        """Process an illustration step."""
