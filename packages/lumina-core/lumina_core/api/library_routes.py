"""Thin metadata assistant API. Query proposals never mutate books."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from lumina_core.library_assistant import LibraryPlan, apply_action, ask_library, delete_tag, execute_plan, list_tags, save_tag

router = APIRouter(prefix="/library", tags=["library"])


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    previous_result_id: str | None = Field(default=None, max_length=64)


class TagRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class TagPreviewRequest(TagRequest):
    remove: bool = False


@router.post("/results/{result_id}/preview-tag")
async def preview_tag(result_id: str, body: TagPreviewRequest, request: Request):
    try:
        plan = LibraryPlan(scope="previous", action="remove_tag" if body.remove else "add_tag", tag=body.name)
        return await asyncio.to_thread(execute_plan, request.app.state.lumina.conn, plan, result_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/ask")
async def ask(body: AskRequest, request: Request):
    state = request.app.state.lumina
    if not body.message.strip():
        raise HTTPException(422, "请输入要问书库的问题")
    try:
        return await ask_library(state.conn, state.router, body.message, body.previous_result_id)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "还没理解这次的筛选条件。请试着按语言、作者、段数或阅读状态提问。") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "暂时无法理解这个问题，请稍后重试，或在设置中检查对话模型。") from exc


@router.post("/results/{result_id}/apply")
async def apply(result_id: str, request: Request):
    try:
        return await asyncio.to_thread(apply_action, request.app.state.lumina.conn, result_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/tags")
async def tags(request: Request):
    return {"tags": await asyncio.to_thread(list_tags, request.app.state.lumina.conn)}


@router.post("/tags")
async def create_tag(body: TagRequest, request: Request):
    try:
        await asyncio.to_thread(save_tag, request.app.state.lumina.conn, body.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await tags(request)


@router.patch("/tags/{tag_id}")
async def rename_tag(tag_id: str, body: TagRequest, request: Request):
    try:
        await asyncio.to_thread(save_tag, request.app.state.lumina.conn, body.name, tag_id)
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, "标签不存在或名称已被使用") from exc
    return await tags(request)


@router.delete("/tags/{tag_id}")
async def remove_tag(tag_id: str, request: Request):
    await asyncio.to_thread(delete_tag, request.app.state.lumina.conn, tag_id)
    return await tags(request)
