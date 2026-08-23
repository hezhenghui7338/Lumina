"""Optional local semantic scorers with deterministic rule fallback."""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import httpx

from lumina_core.config import (
    OLLAMA_BASE_URL,
    SEMANTIC_EMBED_TIMEOUT_SECONDS,
    semantic_onnx_model_dir,
)
from lumina_core.ollama_setup import is_embedding_model, is_local_base_url


class RuleBoundaryScorer:
    """Dependency-free lexical novelty scorer for reliable offline fallback."""

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [1.0 - _counter_cosine(_features(left), _features(right)) for left, right in pairs]


class OllamaBoundaryScorer:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.cancelled = cancelled or (lambda: False)

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        values: list[str] = []
        for left, right in pairs:
            values.extend((_embedding_text(left), _embedding_text(right)))
        vectors: list[list[float]] = []
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            trust_env=not is_local_base_url(self.base_url),
        ) as client:
            for offset in range(0, len(values), 64):
                if self.cancelled():
                    raise InterruptedError("semantic scoring cancelled")
                batch = values[offset : offset + 64]
                response = client.post(
                    "/api/embed",
                    json={"model": self.model, "input": batch},
                )
                response.raise_for_status()
                batch_vectors = response.json().get("embeddings") or []
                if len(batch_vectors) != len(batch):
                    raise RuntimeError("Ollama embedding response count mismatch")
                vectors.extend(batch_vectors)
        if len(vectors) != len(values):
            raise RuntimeError("Ollama embedding response count mismatch")
        return [
            1.0 - _vector_cosine(vectors[i], vectors[i + 1])
            for i in range(0, len(vectors), 2)
        ]


class OnnxBoundaryScorer:
    """Small HuggingFace-style ONNX encoder loaded only when assets exist."""

    def __init__(
        self,
        model_dir: Path,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._session = ort.InferenceSession(
            str(model_dir / "model.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {item.name for item in self._session.get_inputs()}
        self.cancelled = cancelled or (lambda: False)

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        import numpy as np

        if not pairs:
            return []
        texts: list[str] = []
        for left, right in pairs:
            texts.extend((_embedding_text(left), _embedding_text(right)))
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), 64):
            if self.cancelled():
                raise InterruptedError("semantic scoring cancelled")
            encodings = self._tokenizer.encode_batch(texts[offset : offset + 64])
            max_len = min(512, max(len(item.ids) for item in encodings))
            input_ids = np.zeros((len(encodings), max_len), dtype=np.int64)
            attention_mask = np.zeros_like(input_ids)
            for row, encoding in enumerate(encodings):
                ids = encoding.ids[:max_len]
                input_ids[row, : len(ids)] = ids
                attention_mask[row, : len(ids)] = 1
            inputs: dict[str, Any] = {"input_ids": input_ids}
            if "attention_mask" in self._input_names:
                inputs["attention_mask"] = attention_mask
            if "token_type_ids" in self._input_names:
                inputs["token_type_ids"] = np.zeros_like(input_ids)
            output = self._session.run(None, inputs)[0]
            if output.ndim == 3:
                mask = attention_mask[..., None]
                output = (output * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
            vectors.extend(output.tolist())
        return [
            1.0 - _vector_cosine(vectors[i], vectors[i + 1])
            for i in range(0, len(vectors), 2)
        ]


class FallbackBoundaryScorer:
    """Try optional scorers once, then permanently fall back for this job."""

    def __init__(
        self,
        scorers: list[Any],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self._scorers = scorers
        self._cancelled = cancelled or (lambda: False)
        self.selected = type(scorers[0]).__name__ if scorers else ""

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        while self._scorers:
            if self._cancelled():
                raise InterruptedError("semantic scoring cancelled")
            scorer = self._scorers[0]
            try:
                result = scorer.score_pairs(pairs)
                self.selected = type(scorer).__name__
                return [_clamp(value) for value in result]
            except InterruptedError:
                raise
            except Exception:
                self._scorers.pop(0)
        return RuleBoundaryScorer().score_pairs(pairs)


def build_boundary_scorer(
    *,
    ollama_base_url: str = OLLAMA_BASE_URL,
    onnx_model_dir: Path | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> FallbackBoundaryScorer:
    """Build Ollama → ONNX → rules chain without downloading any model."""
    scorers: list[Any] = []
    model = _installed_ollama_embedding_model(ollama_base_url)
    if model:
        scorers.append(
            OllamaBoundaryScorer(
                ollama_base_url,
                model,
                timeout=SEMANTIC_EMBED_TIMEOUT_SECONDS,
                cancelled=cancelled,
            )
        )
    model_dir = onnx_model_dir or semantic_onnx_model_dir()
    if (model_dir / "model.onnx").is_file() and (model_dir / "tokenizer.json").is_file():
        try:
            scorers.append(OnnxBoundaryScorer(model_dir, cancelled=cancelled))
        except Exception:
            pass
    scorers.append(RuleBoundaryScorer())
    return FallbackBoundaryScorer(scorers, cancelled=cancelled)


def _installed_ollama_embedding_model(base_url: str) -> str | None:
    configured = os.getenv("LUMINA_OLLAMA_EMBED_MODEL", "").strip()
    try:
        with httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=min(0.5, SEMANTIC_EMBED_TIMEOUT_SECONDS),
            trust_env=not is_local_base_url(base_url),
        ) as client:
            response = client.get("/api/tags")
            response.raise_for_status()
            installed = [
                str(item.get("name") or "")
                for item in response.json().get("models", [])
                if item.get("name")
            ]
    except Exception:
        return None
    if configured:
        return next((name for name in installed if _same_model(configured, name)), None)
    candidates = [name for name in installed if is_embedding_model(name)]
    preference = ("bge-m3", "nomic-embed-text", "mxbai-embed-large")
    for preferred in preference:
        match = next((name for name in candidates if _same_model(preferred, name)), None)
        if match:
            return match
    return sorted(candidates)[0] if candidates else None


def _same_model(left: str, right: str) -> bool:
    return left.removesuffix(":latest") == right.removesuffix(":latest")


def _embedding_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:2000]


def _features(value: str) -> Counter[str]:
    normalized = re.sub(r"\s+", "", value.lower())
    han = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    features: Counter[str] = Counter(han)
    features.update(han[i : i + 2] for i in range(max(0, len(han) - 1)))
    features.update(re.findall(r"[a-z0-9]{2,}", normalized))
    return features


def _counter_cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / max(left_norm * right_norm, 1e-12)


def _vector_cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return _clamp(dot / max(left_norm * right_norm, 1e-12), low=-1.0, high=1.0)


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
