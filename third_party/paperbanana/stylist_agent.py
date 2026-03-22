# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived from dwzhu-pku/PaperBanana and modified for ARIS runtime use.

from __future__ import annotations

from pathlib import Path

from .base_agent import BaseAgent
from .generation_utils import call_text_model, text_part


class StylistAgent(BaseAgent):
    """Refine the planner output using the bundled style guide."""

    def __init__(self, config) -> None:
        super().__init__(config)
        style_path = (
            Path(__file__).resolve().parent
            / "style_guides"
            / "neurips2025_diagram_style_guide.md"
        )
        self.style_guide = style_path.read_text(encoding="utf-8")

    def process(
        self,
        *,
        detailed_description: str,
        method_context: str,
        figure_caption: str,
    ) -> str:
        prompt = "\n".join(
            [
                "Detailed Description:",
                detailed_description.strip(),
                "",
                "Style Guide:",
                self.style_guide.strip(),
                "",
                "Method Context:",
                method_context.strip(),
                "",
                "Figure Caption:",
                figure_caption.strip(),
            ]
        )
        return call_text_model(
            self.config,
            parts=[text_part(prompt)],
            system_prompt=STYLIST_SYSTEM_PROMPT,
            max_output_tokens=8192,
        )


STYLIST_SYSTEM_PROMPT = """
You are the Stylist agent from a PaperBanana-style academic illustration pipeline.

Task:
- Refine the provided figure description to match top-tier conference aesthetics.
- Preserve semantic content, module structure, labels, and data flow.
- Improve color palette, layout clarity, visual hierarchy, line styles, and icon choice.
- Keep the figure print-friendly and readable in grayscale.
- Output only the revised detailed description.
""".strip()
