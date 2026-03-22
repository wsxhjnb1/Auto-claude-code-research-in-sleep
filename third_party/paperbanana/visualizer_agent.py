# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived from dwzhu-pku/PaperBanana and modified for ARIS runtime use.

from __future__ import annotations

from .base_agent import BaseAgent
from .generation_utils import call_image_model


class VisualizerAgent(BaseAgent):
    """Render an illustration from the styled description."""

    def process(
        self,
        *,
        styled_description: str,
        aspect_ratio: str = "16:9",
    ) -> tuple[bytes, str]:
        return call_image_model(
            self.config,
            prompt=(
                "Render a publication-quality academic method diagram. "
                "Do not include a figure title inside the image.\n\n"
                f"{styled_description.strip()}"
            ),
            system_prompt=VISUALIZER_SYSTEM_PROMPT,
            aspect_ratio=aspect_ratio,
        )


VISUALIZER_SYSTEM_PROMPT = """
You are the Visualizer agent from a PaperBanana-style academic illustration pipeline.

Render clean, publication-ready academic diagrams with explicit modules, thick arrows,
clear labels, and a white or near-white background.
""".strip()
