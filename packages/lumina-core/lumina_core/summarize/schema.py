"""Segment summary JSON schema (TDD §4.3)."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, field_validator


class SegmentSummary(BaseModel):
    sentences: list[str] = Field(min_length=1, max_length=3)
    bullets: list[str] = Field(min_length=3, max_length=7)
    label: str = Field(max_length=20)
    anchor: str

    @field_validator("label")
    @classmethod
    def label_max_chars(cls, v: str) -> str:
        if len(v) > 20:
            raise ValueError(f"label exceeds 20 chars: {len(v)}")
        return v


def parse_segment_summary(raw: str) -> SegmentSummary:
    data = json.loads(raw) if isinstance(raw, str) else raw
    return SegmentSummary.model_validate(data)
