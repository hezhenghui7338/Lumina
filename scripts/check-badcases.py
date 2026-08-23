#!/usr/bin/env python3
"""Release gate: conversation bad cases must be covered before pack."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRED = (
    "id",
    "title",
    "symptom",
    "root_cause",
    "source",
    "status",
    "layer",
    "repro",
    "dedupe_key",
)
STATUSES = {"draft", "covered", "rule", "wontfix"}
LAYERS = {"pytest", "swift", "windows", "rule"}
CODE_SUFFIXES = {".py", ".swift", ".cs"}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> list[tuple[int, dict]]:
    if not path.exists():
        return []
    rows: list[tuple[int, dict]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{lineno}: invalid JSON ({exc})") from exc
        if not isinstance(obj, dict):
            raise SystemExit(f"{path}:{lineno}: expected object, got {type(obj).__name__}")
        rows.append((lineno, obj))
    return rows


def as_test_list(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError("test must be a string, array of strings, or empty")


def symbol_in_code(text: str, name: str, suffix: str) -> bool:
    escaped = re.escape(name)
    if suffix == ".py":
        return bool(
            re.search(rf"^(async\s+)?def\s+{escaped}\s*\(", text, re.M)
            or re.search(rf"^class\s+{escaped}\b", text, re.M)
        )
    if suffix == ".swift":
        return bool(re.search(rf"func\s+{escaped}\s*\(", text))
    if suffix == ".cs":
        return bool(re.search(rf"\b{escaped}\s*\(", text))
    return name in text


def check_test_pointer(root: Path, pointer: str, errors: list[str], loc: str) -> None:
    path_str, _, symbol = pointer.partition("::")
    path = root / path_str
    if not path.is_file():
        errors.append(f"{loc}: test path missing: {path_str}")
        return
    if not symbol:
        return
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in CODE_SUFFIXES:
        if not symbol_in_code(text, symbol, suffix):
            errors.append(f"{loc}: symbol {symbol!r} not found in {path_str}")
    elif symbol not in text:
        errors.append(f"{loc}: {symbol!r} not found in {path_str}")


def check_rule_file(root: Path, name: str, errors: list[str], loc: str) -> None:
    path = root / ".cursor" / "rules" / name if not name.startswith(".cursor/") else root / name
    if not path.is_file():
        errors.append(f"{loc}: rule file missing: {path.relative_to(root)}")


def validate_entry(
    root: Path,
    obj: dict,
    *,
    loc: str,
    in_catalog: bool,
    errors: list[str],
    ids: dict[str, str],
    keys: dict[str, str],
) -> None:
    missing = [field for field in REQUIRED if field not in obj or obj[field] in (None, "")]
    if missing:
        errors.append(f"{loc}: missing {', '.join(missing)}")
        return

    status = obj["status"]
    layer = obj["layer"]
    if status not in STATUSES:
        errors.append(f"{loc}: invalid status {status!r}")
    if layer not in LAYERS:
        errors.append(f"{loc}: invalid layer {layer!r}")

    entry_id = obj["id"]
    if entry_id in ids:
        errors.append(f"{loc}: duplicate id {entry_id!r} (also {ids[entry_id]})")
    else:
        ids[entry_id] = loc

    dedupe = obj["dedupe_key"]
    if dedupe in keys:
        errors.append(f"{loc}: duplicate dedupe_key {dedupe!r} (also {keys[dedupe]})")
    else:
        keys[dedupe] = loc

    try:
        tests = as_test_list(obj.get("test"))
    except ValueError as exc:
        errors.append(f"{loc}: {exc}")
        return

    rule = obj.get("rule")
    if rule is not None and not isinstance(rule, str):
        errors.append(f"{loc}: rule must be a string")
        return

    if in_catalog and status == "draft":
        errors.append(f"{loc}: status=draft belongs in draft.jsonl")

    if status == "covered":
        if not tests:
            errors.append(f"{loc}: covered entry needs test")
        for pointer in tests:
            check_test_pointer(root, pointer, errors, loc)
        if rule:
            check_rule_file(root, rule, errors, loc)
    elif status == "rule":
        rule_name = rule or (tests[0] if tests else "")
        if not rule_name:
            errors.append(f"{loc}: rule entry needs rule or test filename")
        else:
            check_rule_file(root, rule_name, errors, loc)


def main() -> int:
    root = repo_root()
    catalog_path = root / "tests" / "badcases" / "catalog.jsonl"
    draft_path = root / "tests" / "badcases" / "draft.jsonl"
    errors: list[str] = []
    ids: dict[str, str] = {}
    keys: dict[str, str] = {}

    if not catalog_path.is_file():
        errors.append(f"missing {catalog_path.relative_to(root)}")
    else:
        for lineno, obj in load_jsonl(catalog_path):
            loc = f"{catalog_path.relative_to(root)}:{lineno}"
            validate_entry(
                root, obj, loc=loc, in_catalog=True, errors=errors, ids=ids, keys=keys
            )

    draft_rows = load_jsonl(draft_path) if draft_path.exists() else []
    if draft_rows:
        errors.append(
            f"{draft_path.relative_to(root)}: {len(draft_rows)} unpromoted draft(s); "
            "promote to catalog.jsonl or remove before release"
        )
        for lineno, obj in draft_rows:
            loc = f"{draft_path.relative_to(root)}:{lineno}"
            validate_entry(
                root, obj, loc=loc, in_catalog=False, errors=errors, ids=ids, keys=keys
            )

    if errors:
        print("Bad case catalog check failed:", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        return 1

    catalog_count = len(load_jsonl(catalog_path)) if catalog_path.is_file() else 0
    print(f"Bad case catalog OK ({catalog_count} covered entries, draft empty).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
