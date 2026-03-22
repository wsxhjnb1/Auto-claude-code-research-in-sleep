#!/usr/bin/env python3
"""Gemini browser MCP server for browser-backed image generation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ensure_paper_runtime import maybe_reexec_for_phase

maybe_reexec_for_phase(
    "illustration",
    work_dir=Path(os.environ.get("GEMINI_BROWSER_WORK_DIR", os.getcwd())),
)

from third_party.paperbanana import GeminiBrowserBackend, IllustrationConfig


sys.stdout = os.fdopen(sys.stdout.fileno(), "wb", buffering=0)
sys.stdin = os.fdopen(sys.stdin.fileno(), "rb", buffering=0)

SERVER_NAME = os.environ.get("GEMINI_BROWSER_SERVER_NAME", "gemini-browser")
DEFAULT_WORK_DIR = Path(os.environ.get("GEMINI_BROWSER_WORK_DIR", os.getcwd()))
DEBUG_LOG = Path(
    os.environ.get(
        "GEMINI_BROWSER_DEBUG_LOG",
        str(Path(tempfile.gettempdir()) / f"{SERVER_NAME}-mcp-debug.log"),
    )
)

_use_ndjson = False


def debug_log(message: str) -> None:
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


def send_response(response: dict[str, Any]) -> None:
    global _use_ndjson

    payload = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if _use_ndjson:
        sys.stdout.write(payload + b"\n")
    else:
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8")
        sys.stdout.write(header + payload)
    sys.stdout.flush()


def read_message() -> dict[str, Any] | None:
    global _use_ndjson

    line = sys.stdin.readline()
    if not line:
        return None

    line_text = line.decode("utf-8").rstrip("\r\n")
    if line_text.lower().startswith("content-length:"):
        try:
            content_length = int(line_text.split(":", 1)[1].strip())
        except ValueError:
            return None

        while True:
            header_line = sys.stdin.readline()
            if not header_line:
                return None
            if header_line in {b"\r\n", b"\n"}:
                break

        body = sys.stdin.read(content_length)
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    if line_text.startswith("{") or line_text.startswith("["):
        _use_ndjson = True
        try:
            return json.loads(line_text)
        except json.JSONDecodeError:
            return None

    return None


def make_backend() -> GeminiBrowserBackend:
    work_dir = DEFAULT_WORK_DIR.resolve()
    config = IllustrationConfig(
        work_dir=work_dir,
        output_dir=work_dir / "figures" / "ai_generated",
        reference_dir=None,
        backend="browser",
    )
    return GeminiBrowserBackend(config)


def tool_result_text(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ]
    }


def tool_error_text(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def resolve_output_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def handle_initialize(request_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
        },
    }


def handle_tools_list(request_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "tools": [
                {
                    "name": "status",
                    "description": "Check Playwright availability, dedicated profile presence, and Gemini login readiness.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                    },
                },
                {
                    "name": "login",
                    "description": "Open a headed dedicated Gemini profile so the user can log in once and persist the session.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "timeoutSec": {
                                "type": "integer",
                                "minimum": 30,
                                "description": "How long to wait for the manual login to complete.",
                            }
                        },
                    },
                },
                {
                    "name": "render_image",
                    "description": "Use the Gemini web app to generate one image from a prompt and save it to disk.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "The full image-generation prompt to submit in Gemini.",
                            },
                            "outputPath": {
                                "type": "string",
                                "description": "Absolute or relative path where the generated image should be saved.",
                            },
                            "aspectRatio": {
                                "type": "string",
                                "description": "Requested aspect ratio hint such as 16:9, 4:3, or 1:1.",
                            },
                            "timeoutSec": {
                                "type": "integer",
                                "minimum": 30,
                                "description": "Maximum time to wait for generation and download.",
                            },
                        },
                        "required": ["prompt", "outputPath"],
                    },
                },
            ]
        },
    }


def handle_tool_call(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {}) or {}
    backend = make_backend()
    debug_log(f"tool={tool_name} args={json.dumps(arguments, ensure_ascii=False)}")

    try:
        if tool_name == "status":
            result = backend.status().to_dict()
            result["work_dir"] = str(DEFAULT_WORK_DIR.resolve())
            result["profile_dir"] = str(backend.config.browser_profile_dir)
            return {"jsonrpc": "2.0", "id": request_id, "result": tool_result_text(result)}

        if tool_name == "login":
            timeout_sec = arguments.get("timeoutSec")
            result = backend.login(timeout_sec=timeout_sec).to_dict()
            result["profile_dir"] = str(backend.config.browser_profile_dir)
            return {"jsonrpc": "2.0", "id": request_id, "result": tool_result_text(result)}

        if tool_name == "render_image":
            prompt = str(arguments.get("prompt", "")).strip()
            output_path = str(arguments.get("outputPath", "")).strip()
            if not prompt:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": tool_error_text("render_image requires a non-empty prompt."),
                }
            if not output_path:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": tool_error_text("render_image requires outputPath."),
                }
            result = backend.render_image(
                prompt=prompt,
                output_path=resolve_output_path(output_path),
                aspect_ratio=str(arguments.get("aspectRatio", "16:9")),
                timeout_sec=arguments.get("timeoutSec"),
            ).to_dict()
            result["profile_dir"] = str(backend.config.browser_profile_dir)
            return {"jsonrpc": "2.0", "id": request_id, "result": tool_result_text(result)}

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
        }
    except Exception as exc:
        debug_log(f"tool_error={tool_name} error={exc!r}")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": tool_error_text(f"{tool_name} failed: {exc}"),
        }


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    if request_id is None:
        return None

    if method == "initialize":
        return handle_initialize(request_id)
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return handle_tools_list(request_id)
    if method == "tools/call":
        return handle_tool_call(request_id, params)

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main() -> int:
    debug_log(f"=== {SERVER_NAME} MCP server starting ===")
    while True:
        request = read_message()
        if request is None:
            break
        response = handle_request(request)
        if response is not None:
            send_response(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
