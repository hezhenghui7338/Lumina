"""Three-profile model router with resource priority fallback."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

import httpx

from lumina_core.config import (
    ModelResource,
    ModelsConfig,
    OLLAMA_KEEP_ALIVE,
    ProfileRoute,
    SUMMARY_SEGMENT_TIMEOUT_SECONDS,
)
from lumina_core.models.concurrency import ResourceBusyError, ResourceConcurrencyGate
from lumina_core.models.openai_compat import openai_compat_client_base, openai_compat_paths
from lumina_core.ollama_setup import is_local_base_url

Profile = Literal["chat", "summarize", "translate"]

_router: ProfileModelRouter | None = None
logger = logging.getLogger(__name__)

_JSON_FORMAT_RETRY_STATUSES = frozenset({400, 422})


def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
    body = (exc.response.text or "").strip()[:200]
    status = exc.response.status_code
    if body:
        return f"HTTP {status}: {body}"
    return f"HTTP {status}: {exc.response.reason_phrase or 'error'}"


def _format_chain_failure(
    resources: list[ModelResource],
    last_error: Exception | None,
) -> str:
    """Build an actionable error when every resource in a priority chain fails."""
    tried = ", ".join(r.id for r in resources) or "（无）"
    if isinstance(last_error, httpx.HTTPStatusError):
        detail = _http_error_detail(last_error)
    else:
        detail = str(last_error) if last_error else "未知错误"
    hints: list[str] = []

    if "cursor base_url not set" in detail:
        hints.append("Cursor 需配置 OpenAI 兼容 Base URL（官方暂无原生 chat/completions endpoint）")
    if "cursor api_key not set" in detail:
        hints.append("Cursor API Key 未配置")
    if "base_url not set" in detail and "cursor base_url" not in detail:
        hints.append("请在设置中配置对应资源的 Base URL")
    if "api_key not set" in detail and "cursor api_key" not in detail:
        hints.append("请在设置中配置对应资源的 API Key")
    if isinstance(last_error, httpx.ConnectError):
        hints.append("请确认 Ollama 已启动（菜单栏 Llama 图标）或 API 服务可达")
    if isinstance(last_error, (httpx.TimeoutException, TimeoutError)):
        hints.append("请求超时，可稍后重试或调整优先级链")
    if isinstance(last_error, httpx.HTTPStatusError) and last_error.response.status_code == 404:
        hints.append(
            "请检查 Base URL 是否正确（OpenRouter 应为 https://openrouter.ai/api/v1）"
        )
    elif "404" in detail and "Not Found" in detail:
        hints.append(
            "请检查 Base URL 是否正确（OpenRouter 应为 https://openrouter.ai/api/v1）"
        )

    msg = f"优先级链全部失败（已尝试：{tried}）：{detail}"
    if hints:
        msg += "。" + "；".join(hints)
    return msg


class ProfileModelRouter:
    """Route LLM calls through per-profile resource priority chains."""

    def __init__(
        self,
        models: ModelsConfig,
        *,
        gate: ResourceConcurrencyGate | None = None,
    ) -> None:
        self.models = models
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._gate = gate if gate is not None else ResourceConcurrencyGate(models.resources)
        self.last_resource_id: str | None = None
        self.last_provider: str | None = None
        self.last_model: str | None = None
        self.last_call: dict[str, Any] | None = None

    @property
    def gate(self) -> ResourceConcurrencyGate:
        return self._gate

    def update_resources(self, resources: list[ModelResource]) -> None:
        self._gate.set_resources(resources)

    def _resources_for(self, profile: Profile) -> list[ModelResource]:
        return self.models.resources_for_profile(profile)

    def _client_for(self, resource: ModelResource, *, timeout: float = 120.0) -> httpx.AsyncClient:
        key = f"{resource.base_url}|{resource.api_key or ''}|{timeout}"
        if key not in self._clients:
            headers: dict[str, str] = {}
            if resource.api_key:
                headers["Authorization"] = f"Bearer {resource.api_key}"
            if resource.provider == "openrouter":
                headers["HTTP-Referer"] = "https://lumina.local"
                headers["X-Title"] = "Lumina"
            self._clients[key] = httpx.AsyncClient(
                base_url=openai_compat_client_base(resource.base_url)
                if resource.base_url
                else "",
                headers=headers,
                timeout=timeout,
                trust_env=not is_local_base_url(resource.base_url),
            )
        return self._clients[key]

    @staticmethod
    def _openai_completions_path(resource: ModelResource) -> str:
        _, completions_path = openai_compat_paths(resource.base_url or "")
        return completions_path

    @staticmethod
    def _build_openai_payload(
        resource: ModelResource,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": resource.model, "messages": messages}
        if stream:
            payload["stream"] = True
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            if resource.provider == "openrouter":
                payload["provider"] = {"require_parameters": True}
        return payload

    async def _post_openai_json(
        self,
        resource: ModelResource,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        client = self._client_for(resource, timeout=timeout)
        path = self._openai_completions_path(resource)
        had_json_format = "response_format" in payload
        resp = await client.post(path, json=payload)
        if (
            had_json_format
            and resp.status_code in _JSON_FORMAT_RETRY_STATUSES
        ):
            retry_payload = {
                key: value
                for key, value in payload.items()
                if key not in ("response_format", "provider")
            }
            resp = await client.post(path, json=retry_payload)
        if resp.is_error:
            resp.raise_for_status()
        return resp.json()

    async def complete(
        self,
        prompt: str,
        *,
        profile: Profile = "summarize",
        json_mode: bool = False,
        on_slot_acquired: Callable[[], Awaitable[None]] | None = None,
    ) -> str:
        resources = self._resources_for(profile)
        if not resources:
            raise RuntimeError(f"no resources configured for profile {profile}")
        return await self._complete_with_fallback(
            resources,
            prompt,
            json_mode=json_mode,
            profile=profile,
            on_slot_acquired=on_slot_acquired,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        profile: Profile = "chat",
        stream: bool = False,
        json_mode: bool = False,
    ) -> str | AsyncIterator[str]:
        resources = self._resources_for(profile)
        if not resources:
            raise RuntimeError(f"no resources configured for profile {profile}")
        if stream:
            return self._chat_stream_with_fallback(
                resources,
                messages,
                json_mode=json_mode,
            )
        return await self._chat_with_fallback(
            resources,
            messages,
            json_mode=json_mode,
        )

    async def _complete_with_fallback(
        self,
        resources: list[ModelResource],
        prompt: str,
        *,
        json_mode: bool,
        profile: Profile = "summarize",
        on_slot_acquired: Callable[[], Awaitable[None]] | None = None,
    ) -> str:
        last_error: Exception | None = None
        ollama_skipped = False
        ollama_fast_timed_out = False
        attempted: set[str] = set()
        started = time.time()
        slot_notified = False

        async def _notify_slot() -> None:
            nonlocal slot_notified
            if on_slot_acquired is None or slot_notified:
                return
            slot_notified = True
            await on_slot_acquired()

        for index, resource in enumerate(resources):
            if not self._resource_configured(resource):
                continue
            attempted.add(resource.id)
            configured = [r for r in resources if self._resource_configured(r)]
            has_fallback = resource.id != configured[-1].id if configured else False
            # Summarize must wait for Ollama slots; busy-skip causes instant fallback
            # to cloud providers (often unconfigured) and multi-minute retry storms.
            skip_if_busy = has_fallback and profile != "summarize"
            # Summarize jobs routinely exceed 12s on local Ollama; never fast-fail them.
            fast_ollama_timeout = has_fallback and profile != "summarize"
            resource_started = time.time()
            try:
                text = await self._complete_resource(
                    resource,
                    prompt,
                    json_mode=json_mode,
                    skip_if_busy=skip_if_busy,
                    fast_ollama_timeout=fast_ollama_timeout,
                    profile=profile,
                    on_slot_acquired=_notify_slot,
                )
                from lumina_core.debug_agent_log import agent_log

                agent_log(
                    hypothesis_id="C",
                    location="router.py:_complete_with_fallback:ok",
                    message="resource complete ok",
                    data={
                        "profile": profile,
                        "resource_id": resource.id,
                        "provider": resource.provider,
                        "duration_s": round(time.time() - resource_started, 2),
                        "prompt_chars": len(prompt),
                        "fallback_index": index,
                    },
                )
                self._record_success(resource, profile=profile)
                self._record_call(
                    resource_id=resource.id,
                    profile=profile,
                    started=started,
                    ok=True,
                )
                return text
            except ResourceBusyError as exc:
                from lumina_core.debug_agent_log import agent_log

                agent_log(
                    hypothesis_id="C",
                    location="router.py:_complete_with_fallback:busy",
                    message="resource busy, trying fallback",
                    data={
                        "profile": profile,
                        "resource_id": resource.id,
                        "wait_s": round(time.time() - resource_started, 2),
                    },
                )
                if resource.provider == "ollama":
                    ollama_skipped = True
                last_error = exc
                logger.warning("resource %s busy: %s", resource.id, exc)
            except (httpx.TimeoutException, TimeoutError) as exc:
                from lumina_core.debug_agent_log import agent_log

                agent_log(
                    hypothesis_id="C",
                    location="router.py:_complete_with_fallback:timeout",
                    message="resource timed out, trying fallback",
                    data={
                        "profile": profile,
                        "resource_id": resource.id,
                        "duration_s": round(time.time() - resource_started, 2),
                        "fast_ollama": fast_ollama_timeout,
                    },
                )
                if resource.provider == "ollama":
                    ollama_skipped = True
                if fast_ollama_timeout:
                    ollama_fast_timed_out = True
                last_error = exc
                logger.warning("resource %s timed out: %s", resource.id, exc)
            except Exception as exc:
                from lumina_core.debug_agent_log import agent_log

                agent_log(
                    hypothesis_id="C",
                    location="router.py:_complete_with_fallback:error",
                    message="resource failed, trying fallback",
                    data={
                        "profile": profile,
                        "resource_id": resource.id,
                        "duration_s": round(time.time() - resource_started, 2),
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:300],
                    },
                )
                last_error = exc
                logger.warning("resource %s failed: %s", resource.id, exc)

        retry = self._ollama_last_resort(
            resources, attempted, ollama_skipped, ollama_fast_timed_out=ollama_fast_timed_out
        )
        if retry is not None:
            try:
                text = await self._complete_resource(
                    retry,
                    prompt,
                    json_mode=json_mode,
                    skip_if_busy=False,
                    fast_ollama_timeout=False,
                    profile=profile,
                    on_slot_acquired=_notify_slot,
                )
                self._record_success(retry, profile=profile)
                self._record_call(
                    resource_id=retry.id,
                    profile=profile,
                    started=started,
                    ok=True,
                )
                return text
            except Exception as exc:
                last_error = exc

        err = _format_chain_failure(resources, last_error)
        self._record_call(
            resource_id=resources[-1].id if resources else None,
            profile=profile,
            started=started,
            ok=False,
            error=err,
        )
        raise RuntimeError(err)

    async def _chat_with_fallback(
        self,
        resources: list[ModelResource],
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
    ) -> str:
        last_error: Exception | None = None
        ollama_skipped = False
        ollama_fast_timed_out = False
        attempted: set[str] = set()
        started = time.time()

        for index, resource in enumerate(resources):
            attempted.add(resource.id)
            fast_ollama = index < len(resources) - 1
            try:
                text = await self._chat_resource(
                    resource,
                    messages,
                    json_mode=json_mode,
                    fast_ollama=fast_ollama,
                )
                self._record_success(resource, profile="chat")
                self._record_call(
                    resource_id=resource.id,
                    profile="chat",
                    started=started,
                    ok=True,
                )
                return text
            except ResourceBusyError as exc:
                if resource.provider == "ollama":
                    ollama_skipped = True
                last_error = exc
                logger.warning("resource %s busy: %s", resource.id, exc)
            except (httpx.TimeoutException, TimeoutError) as exc:
                if resource.provider == "ollama":
                    ollama_skipped = True
                    if fast_ollama:
                        ollama_fast_timed_out = True
                last_error = exc
                logger.warning("resource %s timed out: %s", resource.id, exc)
            except Exception as exc:
                last_error = exc
                logger.warning("resource %s failed: %s", resource.id, exc)

        retry = self._ollama_last_resort(
            resources, attempted, ollama_skipped, ollama_fast_timed_out=ollama_fast_timed_out
        )
        if retry is not None:
            try:
                text = await self._chat_resource(
                    retry,
                    messages,
                    json_mode=json_mode,
                    fast_ollama=False,
                )
                self._record_success(retry, profile="chat")
                self._record_call(
                    resource_id=retry.id,
                    profile="chat",
                    started=started,
                    ok=True,
                )
                return text
            except Exception as exc:
                last_error = exc

        err = _format_chain_failure(resources, last_error)
        self._record_call(
            resource_id=resources[-1].id if resources else None,
            profile="chat",
            started=started,
            ok=False,
            error=err,
        )
        raise RuntimeError(err)

    async def _chat_stream_with_fallback(
        self,
        resources: list[ModelResource],
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
    ) -> AsyncIterator[str]:
        last_error: Exception | None = None
        ollama_skipped = False
        ollama_fast_timed_out = False
        attempted: set[str] = set()
        started = time.time()

        for index, resource in enumerate(resources):
            attempted.add(resource.id)
            fast_ollama = index < len(resources) - 1
            try:
                stream = self._chat_stream_resource(
                    resource,
                    messages,
                    json_mode=json_mode,
                    fast_ollama=fast_ollama,
                )
                first = True
                async for chunk in self._gate.wrap_stream(
                    resource.id,
                    stream,
                    skip_if_busy=fast_ollama,
                ):
                    if first:
                        self._record_success(resource, profile="chat")
                        self._record_call(
                            resource_id=resource.id,
                            profile="chat",
                            started=started,
                            ok=True,
                        )
                        first = False
                    yield chunk
                if not first:
                    return
            except ResourceBusyError as exc:
                if resource.provider == "ollama":
                    ollama_skipped = True
                last_error = exc
                logger.warning("resource %s stream busy: %s", resource.id, exc)
            except (httpx.TimeoutException, TimeoutError) as exc:
                if resource.provider == "ollama":
                    ollama_skipped = True
                    if fast_ollama:
                        ollama_fast_timed_out = True
                last_error = exc
                logger.warning("resource %s stream timed out: %s", resource.id, exc)
            except Exception as exc:
                last_error = exc
                logger.warning("resource %s stream failed: %s", resource.id, exc)

        retry = self._ollama_last_resort(
            resources, attempted, ollama_skipped, ollama_fast_timed_out=ollama_fast_timed_out
        )
        if retry is not None:
            stream = self._chat_stream_resource(
                retry,
                messages,
                json_mode=json_mode,
                fast_ollama=False,
            )
            first = True
            async for chunk in self._gate.wrap_stream(retry.id, stream, skip_if_busy=False):
                if first:
                    self._record_success(retry, profile="chat")
                    self._record_call(
                        resource_id=retry.id,
                        profile="chat",
                        started=started,
                        ok=True,
                    )
                    first = False
                yield chunk
            if not first:
                return

        err = _format_chain_failure(resources, last_error)
        self._record_call(
            resource_id=resources[-1].id if resources else None,
            profile="chat",
            started=started,
            ok=False,
            error=err,
        )
        raise RuntimeError(err)

    @staticmethod
    def _ollama_last_resort(
        resources: list[ModelResource],
        attempted: set[str],
        ollama_skipped: bool,
        *,
        ollama_fast_timed_out: bool = False,
    ) -> ModelResource | None:
        ollama = next((r for r in resources if r.provider == "ollama"), None)
        if ollama is None:
            return None
        if ollama.id in attempted and not ollama_fast_timed_out:
            return None
        return ollama

    def _record_success(self, resource: ModelResource, *, profile: str = "summarize") -> None:
        self.last_resource_id = resource.id
        self.last_provider = resource.provider
        self.last_model = resource.model

    def _record_call(
        self,
        *,
        resource_id: str | None,
        profile: str,
        started: float,
        ok: bool,
        error: str | None = None,
    ) -> None:
        from datetime import datetime, timezone

        self.last_call = {
            "resource_id": resource_id,
            "profile": profile,
            "started_at": datetime.fromtimestamp(started, tz=timezone.utc).isoformat(),
            "duration_ms": int((time.time() - started) * 1000),
            "ok": ok,
            "error": error,
        }

    def resource_runtime(self) -> list[dict[str, int | str]]:
        return self._gate.snapshot()

    @staticmethod
    def _resource_configured(resource: ModelResource) -> bool:
        if resource.provider == "ollama":
            return True
        return bool(resource.api_key)

    def _timeout_for(
        self,
        resource: ModelResource,
        *,
        fast_ollama: bool,
        profile: Profile = "summarize",
    ) -> float:
        if resource.provider == "ollama" and profile == "summarize":
            return float(SUMMARY_SEGMENT_TIMEOUT_SECONDS)
        if resource.provider == "ollama" and fast_ollama:
            return max(1.0, float(resource.chat_timeout))
        return 120.0

    async def _complete_resource(
        self,
        resource: ModelResource,
        prompt: str,
        *,
        json_mode: bool,
        skip_if_busy: bool,
        fast_ollama_timeout: bool,
        profile: Profile = "summarize",
        on_slot_acquired: Callable[[], Awaitable[None]] | None = None,
    ) -> str:
        async with self._gate.use(resource.id, skip_if_busy=skip_if_busy):
            if on_slot_acquired is not None:
                await on_slot_acquired()
            timeout = self._timeout_for(
                resource, fast_ollama=fast_ollama_timeout, profile=profile
            )
            if resource.provider == "ollama":
                return await self._ollama_complete(
                    resource,
                    prompt,
                    json_mode=json_mode,
                    timeout=timeout,
                    profile=profile,
                )
            self._require_base_url(resource)
            self._require_api_key(resource)
            return await self._openai_complete(
                resource,
                prompt,
                json_mode=json_mode,
                timeout=timeout,
            )

    async def _chat_resource(
        self,
        resource: ModelResource,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        fast_ollama: bool,
    ) -> str:
        async with self._gate.use(resource.id, skip_if_busy=fast_ollama):
            timeout = self._timeout_for(resource, fast_ollama=fast_ollama)
            if resource.provider == "ollama":
                return await self._ollama_chat(
                    resource,
                    messages,
                    json_mode=json_mode,
                    timeout=timeout,
                )
            self._require_base_url(resource)
            self._require_api_key(resource)
            return await self._openai_chat(
                resource,
                messages,
                json_mode=json_mode,
                timeout=timeout,
            )

    def _chat_stream_resource(
        self,
        resource: ModelResource,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        fast_ollama: bool,
    ) -> AsyncIterator[str]:
        timeout = self._timeout_for(resource, fast_ollama=fast_ollama)
        if resource.provider == "ollama":
            return self._ollama_chat_stream(
                resource,
                messages,
                json_mode=json_mode,
                timeout=timeout,
            )
        self._require_base_url(resource)
        self._require_api_key(resource)
        return self._openai_chat_stream(
            resource,
            messages,
            json_mode=json_mode,
            timeout=timeout,
        )

    @staticmethod
    def _require_api_key(resource: ModelResource) -> None:
        if not resource.api_key:
            raise RuntimeError(f"{resource.provider} api_key not set")

    @staticmethod
    def _require_base_url(resource: ModelResource) -> None:
        if not (resource.base_url or "").strip():
            raise RuntimeError(f"{resource.provider} base_url not set")

    def _ollama_payload(
        self,
        resource: ModelResource,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        stream: bool,
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        if profile == "summarize" and json_mode:
            num_predict = 384
        elif json_mode:
            num_predict = 768
        else:
            num_predict = 1024
        payload: dict[str, Any] = {
            "model": resource.model,
            "messages": messages,
            "stream": stream,
            "think": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "num_ctx": 8192,
                "num_predict": num_predict,
            },
        }
        if json_mode:
            payload["format"] = "json"
        return payload

    async def _ollama_complete(
        self,
        resource: ModelResource,
        prompt: str,
        *,
        json_mode: bool,
        timeout: float,
        profile: Profile = "summarize",
    ) -> str:
        client = self._client_for(resource, timeout=timeout)
        payload = self._ollama_payload(
            resource,
            [{"role": "user", "content": prompt}],
            json_mode=json_mode,
            stream=False,
            profile=profile,
        )
        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    async def _ollama_chat(
        self,
        resource: ModelResource,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        timeout: float,
    ) -> str:
        client = self._client_for(resource, timeout=timeout)
        payload = self._ollama_payload(resource, messages, json_mode=json_mode, stream=False)
        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    async def _ollama_chat_stream(
        self,
        resource: ModelResource,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        timeout: float,
    ) -> AsyncIterator[str]:
        client = self._client_for(resource, timeout=timeout)
        payload = self._ollama_payload(resource, messages, json_mode=json_mode, stream=True)
        async with client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk

    async def _openai_stream_with_fallback(
        self,
        resource: ModelResource,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> AsyncIterator[str]:
        client = self._client_for(resource, timeout=timeout)
        path = self._openai_completions_path(resource)
        had_json_format = "response_format" in payload

        async def _iter_stream(request_payload: dict[str, Any]) -> AsyncIterator[str]:
            async with client.stream("POST", path, json=request_payload) as resp:
                if resp.is_error:
                    await resp.aread()
                    resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta

        try:
            async for chunk in _iter_stream(payload):
                yield chunk
        except httpx.HTTPStatusError as exc:
            if (
                not had_json_format
                or exc.response.status_code not in _JSON_FORMAT_RETRY_STATUSES
            ):
                raise RuntimeError(_http_error_detail(exc)) from exc
            retry_payload = {
                key: value
                for key, value in payload.items()
                if key not in ("response_format", "provider")
            }
            try:
                async for chunk in _iter_stream(retry_payload):
                    yield chunk
            except httpx.HTTPStatusError as retry_exc:
                raise RuntimeError(_http_error_detail(retry_exc)) from retry_exc

    async def _openai_complete(
        self,
        resource: ModelResource,
        prompt: str,
        *,
        json_mode: bool,
        timeout: float,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        payload = self._build_openai_payload(resource, messages, json_mode=json_mode)
        try:
            data = await self._post_openai_json(resource, payload, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_http_error_detail(exc)) from exc
        return data["choices"][0]["message"]["content"]

    async def _openai_chat(
        self,
        resource: ModelResource,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        timeout: float,
    ) -> str:
        payload = self._build_openai_payload(resource, messages, json_mode=json_mode)
        try:
            data = await self._post_openai_json(resource, payload, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_http_error_detail(exc)) from exc
        return data["choices"][0]["message"]["content"]

    async def _openai_chat_stream(
        self,
        resource: ModelResource,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        timeout: float,
    ) -> AsyncIterator[str]:
        payload = self._build_openai_payload(
            resource, messages, json_mode=json_mode, stream=True
        )
        async for chunk in self._openai_stream_with_fallback(
            resource, payload, timeout=timeout
        ):
            yield chunk

    async def aclose(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()


class OllamaRouter(ProfileModelRouter):
    """Backward-compatible alias for tests."""

    def __init__(
        self,
        base_url: str,
        models: dict[Profile, str] | None = None,
    ) -> None:
        m = models or {
            "summarize": "qwen3.5:4b",
            "chat": "qwen3.5:4b",
            "translate": "qwen3.5:4b",
        }
        resource = ModelResource(
            id="ollama",
            provider="ollama",
            base_url=base_url,
            model=m["summarize"],
        )
        route = ProfileRoute(priority=["ollama"])
        cfg = ModelsConfig(
            resources=[resource],
            chat=route,
            summarize=route,
            translate=route,
        )
        # Fix model per profile by cloning resources — tests use one model name.
        super().__init__(cfg)


def get_router() -> ProfileModelRouter:
    if _router is None:
        raise RuntimeError("ModelRouter not configured; call set_router() first")
    return _router


def set_router(router: ProfileModelRouter | OllamaRouter | Any | None) -> None:
    global _router
    _router = router  # type: ignore[assignment]


def _strip_json_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _escape_unescaped_quotes_in_json_strings(text: str) -> str:
    """Escape double quotes that LLMs leave unescaped inside JSON string values."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(ch)
            out.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j] in " \t\n\r":
                j += 1
            if j >= n or text[j] in ",}:]":
                out.append(ch)
                in_string = False
                i += 1
                continue
            out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _repair_body_string_delimiters(text: str) -> str:
    """Fix LLM body values that use curly quotes or omit the opening quote."""
    repaired = re.sub(
        r'("body"\s*:\s*)\u201c([^\u201d]*)\u201d([^"]*?)"(\s*[,}\]])',
        lambda m: f'{m.group(1)}"「{m.group(2)}」{m.group(3)}"{m.group(4)}',
        text,
    )
    repaired = re.sub(
        r'("body"\s*:\s*)([^"\s\[{\u201c][^"]*?)"(\s*[,}\]])',
        r'\1"\2"\3',
        repaired,
    )
    return repaired


def _repair_llm_json(text: str) -> str:
    """Fix common LLM JSON mistakes before parsing."""
    repaired = _repair_body_string_delimiters(text)
    repaired = re.sub(r'(?<=")\s+(?=")', ", ", repaired)
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(
        r'"bullets"\s*:\s*\[\[(.*?)\]\s*,\s*"(?:锚点|anchor)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
        r'"bullets":[\1], "anchor":"\2"}',
        repaired,
        flags=re.DOTALL,
    )
    repaired = re.sub(
        r'"bullets"\s*:\s*\[\[(.*?)\]\]',
        r'"bullets":[\1]',
        repaired,
        flags=re.DOTALL,
    )
    repaired = re.sub(r"\}\s*\]\s*$", "}", repaired)
    repaired = re.sub(r'"锚点"\s*:', '"anchor":', repaired)
    _bullet_obj = (
        r'(\{"label"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*"body"\s*:\s*"(?:[^"\\]|\\.)*")\s*\]'
    )
    repaired = re.sub(
        _bullet_obj + r',\s*(\{"label")',
        r"\1}, \2",
        repaired,
    )
    repaired = re.sub(
        _bullet_obj + r',\s*"(follow_ups|notes|label|anchor)"',
        r'\1}], "\2"',
        repaired,
    )
    repaired = re.sub(
        r'"follow_ups"\s*:\s*\["\]\[.*?\]\s*,\s*"label"',
        '"follow_ups":[],"label"',
        repaired,
        flags=re.DOTALL,
    )
    repaired = _escape_unescaped_quotes_in_json_strings(repaired)
    repaired = re.sub(
        r'("body"\s*:\s*"(?:[^"\\]|\\.)*")\s*,\s*"label"',
        r'\1},{"label"',
        repaired,
    )
    return repaired


def _merge_adjacent_json_objects(text: str) -> dict[str, Any] | None:
    """Merge consecutive JSON objects, e.g. `{a:1}, {b:2}` → `{a:1, b:2}`."""
    decoder = json.JSONDecoder()
    merged: dict[str, Any] = {}
    idx = 0
    length = len(text)
    found = False
    while idx < length:
        while idx < length and text[idx] in " \t\n\r,":
            idx += 1
        if idx >= length:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            if found and idx < length:
                return None
            return merged if found else None
        if isinstance(obj, dict):
            merged.update(obj)
            found = True
        else:
            return merged if found else None
        idx = end
    return merged if found else None


def _parse_first_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first complete JSON object, ignoring trailing prose."""
    start = text.find("{")
    if start < 0:
        return None
    for candidate in (text[start:], _repair_llm_json(text[start:])):
        try:
            obj, _ = json.JSONDecoder().raw_decode(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def parse_json_response(raw: str) -> dict[str, Any]:
    text = _strip_json_fence(raw)
    candidates = [text, _repair_llm_json(text)]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    for candidate in candidates:
        merged = _merge_adjacent_json_objects(candidate)
        if merged is not None:
            return merged
    for candidate in candidates:
        first = _parse_first_json_object(candidate)
        if first is not None:
            return first
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        sliced = text[start : end + 1]
        slice_candidates = [sliced, _repair_llm_json(sliced)]
        for candidate in slice_candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        for candidate in slice_candidates:
            merged = _merge_adjacent_json_objects(candidate)
            if merged is not None:
                return merged
        for candidate in slice_candidates:
            first = _parse_first_json_object(candidate)
            if first is not None:
                return first
    raise json.JSONDecodeError("Unable to parse JSON response", text, 0)


def parse_chat_response(raw: str) -> dict[str, Any]:
    """Parse chat JSON; on failure return raw text as answer (no raise)."""
    try:
        parsed = parse_json_response(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    text = (raw or "").strip()
    return {
        "answer": text or "（模型未返回有效内容，请重试）",
        "citations": [],
        "web_refs": [],
        "evidence_sufficient": False,
    }
