"""Deprecated debug hook; kept as a no-op so stray imports cannot block xdist workers."""

from __future__ import annotations

from typing import Any


def agent_log(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    run_id: str = "pre-fix",
) -> None:
    return
