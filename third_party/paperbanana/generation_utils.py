# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# Derived from dwzhu-pku/PaperBanana and modified for ARIS runtime use.

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import IllustrationConfig


def text_part(text: str) -> dict[str, str]:
    return {"text": text}


def image_part(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(image_bytes).decode("utf-8"),
        }
    }


def call_text_model(
    config: IllustrationConfig,
    *,
    parts: list[dict[str, Any]],
    system_prompt: str,
    expect_json: bool = False,
    max_output_tokens: int = 8192,
) -> str:
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": config.temperature,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json" if expect_json else "text/plain",
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [text_part(system_prompt)]}
    response = _post_generate_content(
        config=config,
        model_name=config.text_model_name,
        payload=payload,
        max_attempts=4,
    )
    texts = []
    for part in _iter_candidate_parts(response):
        text = part.get("text")
        if text:
            texts.append(text)
    if not texts:
        raise RuntimeError("Text model returned no text output.")
    return "\n".join(texts).strip()


def call_image_model(
    config: IllustrationConfig,
    *,
    prompt: str,
    system_prompt: str,
    aspect_ratio: str,
) -> tuple[bytes, str]:
    payload = {
        "contents": [{"role": "user", "parts": [text_part(prompt)]}],
        "generationConfig": {
            "temperature": config.temperature,
            "maxOutputTokens": 8192,
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
            },
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [text_part(system_prompt)]}
    response = _post_generate_content(
        config=config,
        model_name=config.image_model_name,
        payload=payload,
        max_attempts=4,
    )
    for part in _iter_candidate_parts(response):
        inline = part.get("inlineData")
        if not inline:
            continue
        mime_type = inline.get("mimeType", "image/png")
        data = inline.get("data", "")
        if data:
            return base64.b64decode(data), mime_type
    raise RuntimeError("Image model returned no inline image payload.")


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _post_generate_content(
    *,
    config: IllustrationConfig,
    model_name: str,
    payload: dict[str, Any],
    max_attempts: int,
) -> dict[str, Any]:
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Missing illustration backend credentials. Set PAPER_ILLUSTRATION_API_KEY "
            "or PAPER_ILLUSTRATION_API_KEY_ENV."
        )
    url = (
        f"{config.api_base.rstrip('/')}/models/"
        f"{urllib.parse.quote(model_name, safe='')}:generateContent?key={api_key}"
    )
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=config.request_timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == max_attempts - 1:
                break
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Illustration backend request failed: {last_error}") from last_error


def _iter_candidate_parts(response: dict[str, Any]):
    for candidate in response.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            yield part
