#!/usr/bin/env python3
"""stop: auto-follow up build-release failures for at most 3 rounds."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_PATH = STATE_DIR / "build-release.json"


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))


def _load_state() -> dict | None:
    if not STATE_PATH.is_file():
        return None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _excerpt_block(state: dict) -> str:
    excerpt = str(state.get("excerpt") or "").strip()
    if not excerpt:
        return "(no excerpt)"
    if len(excerpt) > 2000:
        excerpt = excerpt[-2000:]
    return excerpt


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        _emit({})
        return 0

    status = str(data.get("status") or "")
    if status == "aborted":
        _emit({})
        return 0

    try:
        loop_count = int(data.get("loop_count") or 0)
    except (TypeError, ValueError):
        loop_count = 0

    state = _load_state()
    if not state or state.get("status") != "failed":
        _emit({})
        return 0

    command = str(state.get("command") or "./scripts/build-release.sh").strip()
    round_num = loop_count + 1
    excerpt = _excerpt_block(state)

    # Cursor enforces loop_limit=3 on this script; when loop_count >= 3,
    # do not emit another follow-up (hard stop).
    if loop_count >= 3:
        state["status"] = "exhausted"
        _save_state(state)
        _emit({})
        return 0

    # Final auto follow-up (3rd): report only, no more fix/rerun.
    if loop_count == 2:
        state["status"] = "exhausted"
        _save_state(state)
        msg = (
            "build-release 自动修复已用尽（3/3）。"
            "请遵循项目 skill `build-release` 的失败报告模板，"
            "把阶段、命令、日志摘录、已尝试改动和建议人工下一步完整报给用户。"
            "不要再改代码，不要再跑构建。\n\n"
            f"命令: {command}\n"
            f"日志摘录:\n```\n{excerpt}\n```"
        )
        _emit({"followup_message": msg})
        return 0

    # Rounds 1–2: fix and re-run.
    msg = (
        f"build-release 失败，自动修复第 {round_num}/3 轮。"
        "请遵循项目 skill `build-release`："
        "基于下列摘录做最小修复，然后重新执行同一条构建命令。"
        "禁止跳过 check-badcases / pytest，禁止放宽体积或门禁，"
        "禁止未请求的 commit。\n\n"
        f"命令: {command}\n"
        f"日志摘录:\n```\n{excerpt}\n```"
    )
    _emit({"followup_message": msg})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        try:
            _emit({})
        except Exception:
            pass
        raise SystemExit(0)
