# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived from dwzhu-pku/PaperBanana and modified for ARIS runtime use.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent


class RetrieverAgent(BaseAgent):
    """Optional lightweight retriever for reference-driven prompting."""

    def process(self, *, query_text: str, top_k: int = 3) -> list[dict[str, Any]]:
        reference_dir = self.config.reference_dir
        if self.config.retrieval_setting == "none" or reference_dir is None or not reference_dir.exists():
            return []
        candidates = list(_iter_reference_items(reference_dir))
        if not candidates:
            return []
        query_tokens = _tokenize(query_text)
        scored = []
        for item in candidates:
            haystack = " ".join(
                [
                    item.get("title", ""),
                    item.get("caption", ""),
                    item.get("summary", ""),
                    item.get("description", ""),
                    item.get("visual_intent", ""),
                ]
            )
            score = len(query_tokens & _tokenize(haystack))
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:top_k]]


def _iter_reference_items(reference_dir: Path):
    for path in sorted(reference_dir.rglob("*")):
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, list):
                for entry in payload:
                    if isinstance(entry, dict):
                        yield dict(entry, path=str(path))
            elif isinstance(payload, dict):
                yield dict(payload, path=str(path))
        elif path.suffix.lower() in {".md", ".txt"}:
            text = path.read_text(encoding="utf-8")
            yield {
                "title": path.stem,
                "summary": text[:1200],
                "path": str(path),
            }


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))
