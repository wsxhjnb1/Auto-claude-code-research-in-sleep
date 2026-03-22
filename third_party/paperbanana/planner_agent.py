# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived from dwzhu-pku/PaperBanana and modified for ARIS runtime use.

from __future__ import annotations

from .base_agent import BaseAgent
from .generation_utils import call_text_model, text_part


class PlannerAgent(BaseAgent):
    """Generate a detailed first-pass figure description."""

    def process(
        self,
        *,
        method_context: str,
        figure_id: str,
        figure_type: str,
        figure_caption: str,
        figure_description: str,
        references: list[dict[str, str]],
    ) -> str:
        prompt_lines = [
            f"Figure ID: {figure_id}",
            f"Figure Type: {figure_type}",
            f"Figure Caption: {figure_caption}",
            f"Figure Plan Description: {figure_description}",
            "",
            "Method Context:",
            method_context.strip(),
        ]
        if references:
            prompt_lines.extend(["", "Reference Examples:"])
            for idx, reference in enumerate(references, start=1):
                prompt_lines.append(
                    f"{idx}. {reference.get('title') or reference.get('id') or 'reference'}"
                )
                for key in ("caption", "summary", "description", "visual_intent"):
                    value = reference.get(key)
                    if value:
                        prompt_lines.append(f"   - {key}: {value}")
        prompt_lines.extend(
            [
                "",
                "Write a single detailed figure specification that preserves the intended logic,",
                "uses explicit module labels, explicit arrow directions, and avoids placing the",
                "paper caption text inside the image.",
            ]
        )
        return call_text_model(
            self.config,
            parts=[text_part("\n".join(prompt_lines))],
            system_prompt=PLANNER_SYSTEM_PROMPT,
            max_output_tokens=8192,
        )


PLANNER_SYSTEM_PROMPT = """
You are the Planner agent from a PaperBanana-style academic illustration pipeline.

Task:
- Translate a paper's method description and figure caption into one publication-ready
  figure specification.
- Be explicit about modules, connections, grouping, labels, data flow, comparison points,
  and relative placement.
- Do not output code.
- Do not write conversational text.
- Do not place the paper caption itself inside the image.

The output must be a detailed figure description that a downstream stylist and image
renderer can execute without guessing.
""".strip()
