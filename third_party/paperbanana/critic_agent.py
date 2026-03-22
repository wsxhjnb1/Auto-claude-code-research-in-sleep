# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived from dwzhu-pku/PaperBanana and modified for ARIS runtime use.

from __future__ import annotations

from typing import Any

from .base_agent import BaseAgent
from .generation_utils import call_text_model, image_part, parse_json_object, text_part


class CriticAgent(BaseAgent):
    """Review the rendered illustration and propose revisions."""

    def process(
        self,
        *,
        image_bytes: bytes,
        image_mime_type: str,
        detailed_description: str,
        method_context: str,
        figure_caption: str,
    ) -> dict[str, Any]:
        prompt = "\n".join(
            [
                "Detailed Description:",
                detailed_description.strip(),
                "",
                "Method Context:",
                method_context.strip(),
                "",
                "Figure Caption:",
                figure_caption.strip(),
                "",
                "Return strict JSON only.",
            ]
        )
        raw = call_text_model(
            self.config,
            parts=[
                text_part("Review the rendered figure image."),
                image_part(image_bytes, image_mime_type),
                text_part(prompt),
            ],
            system_prompt=CRITIC_SYSTEM_PROMPT,
            expect_json=True,
            max_output_tokens=4096,
        )
        parsed = parse_json_object(raw)
        score = parsed.get("score", 0)
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 0
        return {
            "score": score,
            "critic_suggestions": parsed.get(
                "critic_suggestions",
                "No structured critique returned.",
            ),
            "revised_description": parsed.get(
                "revised_description",
                detailed_description,
            ),
        }


CRITIC_SYSTEM_PROMPT = """
You are the Critic agent from a PaperBanana-style academic illustration pipeline.

Review the rendered figure for:
- fidelity to the method context and figure caption
- correct arrow directions and module ordering
- readable labels and clean academic styling
- absence of title text inside the image
- overall publication quality for a top-tier ML venue

Return strict JSON with exactly these keys:
{
  "score": <integer 1-10>,
  "critic_suggestions": "<short but specific feedback>",
  "revised_description": "<full revised detailed description>"
}

If the figure already meets the brief, keep the revised description close to the input.
""".strip()
