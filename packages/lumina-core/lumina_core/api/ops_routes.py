"""Ops / diagnostics API routes."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from lumina_core.app_state import AppState
from lumina_core.ops.task_registry import TaskKind, TaskStatus
from lumina_core.resource_probe import probe_resource

router = APIRouter(prefix="/ops", tags=["ops"])

_probe_cache: dict[str, Any] = {"at": 0.0, "resources": []}
_PROBE_TTL_SECONDS = 5.0


def _state(request: Request) -> AppState:
    return request.app.state.lumina  # type: ignore[attr-defined]


def _require_debug_mode(state: AppState) -> None:
    if not state.settings.debug_mode:
        raise HTTPException(403, "Debug mode is disabled")


async def _cached_probes(state: AppState) -> list[dict[str, Any]]:
    now = time.time()
    if now - _probe_cache["at"] < _PROBE_TTL_SECONDS:
        return _probe_cache["resources"]
    results: list[dict[str, Any]] = []
    for resource in state.models.resources:
        status = await probe_resource(resource)
        results.append(status.to_dict())
    _probe_cache["at"] = now
    _probe_cache["resources"] = results
    return results


@router.get("/overview")
async def ops_overview(request: Request) -> dict[str, Any]:
    state = _state(request)
    _require_debug_mode(state)
    return {
        "task_counts": state.task_registry.counts(),
        "job_queue": state.job_queue.diagnostics(),
        "resource_runtime": state.router.resource_runtime(),
        "last_call": state.router.last_call,
    }


@router.get("/tasks")
async def ops_tasks(
    request: Request,
    status: TaskStatus | None = Query(None),
    kind: TaskKind | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    state = _state(request)
    _require_debug_mode(state)
    return {
        "tasks": state.task_registry.snapshot(status=status, kind=kind, limit=limit),
        "counts": state.task_registry.counts(),
    }


@router.post("/tasks/{task_id}/cancel")
async def ops_cancel_task(task_id: str, request: Request) -> dict[str, Any]:
    state = _state(request)
    _require_debug_mode(state)
    record = state.task_registry.get(task_id)
    if not record:
        raise HTTPException(404, "Task not found")
    if not record.cancellable:
        raise HTTPException(400, "Task is not cancellable")
    if record.status not in ("queued", "running"):
        raise HTTPException(400, "Task is not active")
    ok = state.task_registry.cancel(task_id)
    return {"status": "cancelled" if ok else "not_found", "task_id": task_id}


@router.get("/resources/runtime")
async def ops_resource_runtime(request: Request) -> dict[str, Any]:
    state = _state(request)
    _require_debug_mode(state)
    runtime = state.router.resource_runtime()
    probes = await _cached_probes(state)
    probe_by_id = {p["resource_id"]: p for p in probes}
    merged: list[dict[str, Any]] = []
    for row in runtime:
        rid = str(row["resource_id"])
        entry = dict(row)
        entry["probe"] = probe_by_id.get(rid, {})
        merged.append(entry)
    for probe in probes:
        rid = probe.get("resource_id")
        if rid and not any(str(r["resource_id"]) == rid for r in merged):
            merged.append(
                {
                    "resource_id": rid,
                    "limit": 0,
                    "in_use": 0,
                    "available": 0,
                    "probe": probe,
                }
            )
    return {"resources": merged, "last_call": state.router.last_call}
