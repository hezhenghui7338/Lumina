#!/usr/bin/env python3
"""postToolUse: record build-release Shell outcomes for the stop-hook retry loop."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_PATH = STATE_DIR / "build-release.json"

RELEASE_CMD = re.compile(
    r"(?:scripts/)?build-release\.sh|\bjust\s+release\b",
    re.IGNORECASE,
)
EXCERPT_MAX = 4000


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))


def _parse_exit_code(tool_output: object) -> int | None:
    if tool_output is None:
        return None
    payload: object = tool_output
    if isinstance(tool_output, str):
        text = tool_output.strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            # Some hosts pass plain text; treat non-empty as unknown.
            return None
    if not isinstance(payload, dict):
        return None
    for key in ("exitCode", "exit_code", "code", "status"):
        if key not in payload:
            continue
        val = payload[key]
        if isinstance(val, bool):
            continue
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    return None


def _output_excerpt(tool_output: object) -> str:
    if tool_output is None:
        return ""
    if isinstance(tool_output, str):
        text = tool_output
        try:
            parsed = json.loads(tool_output)
            if isinstance(parsed, dict):
                for key in ("stderr", "stdout", "output", "message"):
                    chunk = parsed.get(key)
                    if isinstance(chunk, str) and chunk.strip():
                        text = chunk
                        break
                else:
                    text = json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    elif isinstance(tool_output, dict):
        text = json.dumps(tool_output, ensure_ascii=False)
    else:
        text = str(tool_output)
    text = text.replace("\x00", "")
    if len(text) > EXCERPT_MAX:
        return text[-EXCERPT_MAX:]
    return text


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        _emit({})
        return 0

    tool_name = str(data.get("tool_name") or "")
    if tool_name and tool_name != "Shell":
        _emit({})
        return 0

    tool_input = data.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            tool_input = {"command": tool_input}
    if not isinstance(tool_input, dict):
        _emit({})
        return 0

    command = str(tool_input.get("command") or "")
    if not RELEASE_CMD.search(command):
        _emit({})
        return 0

    exit_code = _parse_exit_code(data.get("tool_output"))
    # If host omitted exit code, do not invent success/failure.
    if exit_code is None:
        _emit({})
        return 0

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    if exit_code == 0:
        state = {
            "status": "ok",
            "command": command,
            "exit_code": 0,
            "excerpt": "",
            "updated_at": now,
        }
    else:
        state = {
            "status": "failed",
            "command": command,
            "exit_code": exit_code,
            "excerpt": _output_excerpt(data.get("tool_output")),
            "updated_at": now,
        }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _emit({})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # fail-open
        try:
            _emit({})
        except Exception:
            pass
        raise SystemExit(0)
