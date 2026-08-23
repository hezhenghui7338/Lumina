"""Tests for hybrid segment-summary clarity supervision."""

from __future__ import annotations

import json

import pytest
from lumina_core.config import (
    ModelResource,
    ModelsConfig,
    ProfileRoute,
    load_prompts_config,
)
from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.quality import (
    inspect_summary_quality,
    merge_clarity_issues,
    scan_summary_clarity,
)
from lumina_core.summarize.schema import SegmentSummary
from lumina_core.summarize.segment import (
    summarize_job_timeout_seconds,
    summarize_segment,
)


def _summary(**overrides) -> SegmentSummary:
    data = {
        "sentences": ["本段交代主角离乡赴考，并说明家人对他的期望。"],
        "bullets": [
            {
                "label": "离乡赴考",
                "body": "主角告别家人后启程赴考，个人选择由此与家族期待发生联系。",
            },
            {
                "label": "家人期望",
                "body": "母亲希望他平安归来，族人则更看重科举功名带来的声望。",
            },
            {
                "label": "后文伏笔",
                "body": "途中出现的陌生来信留下疑问，为后续冲突提供了明确线索。",
            },
        ],
        "notes": [],
        "follow_ups": ["家人与主角的目标有何差异？"],
        "label": "离乡赴考",
        "anchor": "§第一章 · 段 1",
    }
    data.update(overrides)
    return SegmentSummary.model_validate(data)


def test_clarity_scan_passes_readable_summary():
    assert scan_summary_clarity(_summary()) == []


def test_clarity_scan_allows_exactly_one_issue():
    summary = _summary(sentences=["本段交代主角离乡�赴考。"])
    issues = scan_summary_clarity(summary)
    assert len(issues) == 1
    assert issues[0].code == "replacement_char"


def test_clarity_scan_counts_two_distinct_locations():
    summary = _summary(
        sentences=["本段交代主角离乡�赴考。"],
        notes=["来信内容出现�，暂时无法辨认。"],
    )
    issues = scan_summary_clarity(summary)
    assert [issue.code for issue in issues].count("replacement_char") == 2


def test_clarity_scan_deduplicates_overlapping_template_match():
    summary = _summary(notes=['{"label":"残留模板"}'])
    issues = [issue for issue in scan_summary_clarity(summary) if issue.code == "template_leak"]
    assert len(issues) == 1


def test_clarity_scan_detects_label_used_as_body():
    bullets = [bullet.model_dump() for bullet in _summary().bullets]
    bullets[0] = {"label": "离乡赴考", "body": "离乡赴考"}
    issues = scan_summary_clarity(_summary(bullets=bullets))
    assert any(issue.code == "label_as_body" for issue in issues)


def test_clarity_scan_does_not_flag_classical_text_or_names():
    summary = _summary(
        sentences=["子曰：学而时习之，不亦说乎？"],
        notes=["人物名为让-巴蒂斯特·贝尔纳，号东篱。"],
    )
    assert scan_summary_clarity(summary) == []


_FACELESS_RAW = (
    "我醒来时，对面沙发上坐着一位戴着宽檐黑帽、身穿灰暗风衣的高个男子。"
    "他自称没有面孔，并要求我为他画肖像，交还企鹅护身符作为交换。"
    "他的脸只有旋转的乳白色雾气，我不知从何下笔。"
    "男子催促时间紧迫，短暂离开前承诺未来会再来找我。"
)


def test_clarity_scan_flags_assistant_identity_leak():
    summary = _summary(
        sentences=["段落讲述阅读助手遭遇名为无面人的男子要求画肖像。"],
        bullets=[
            {
                "label": "遭遇无面人",
                "body": "阅读助手醒来时，对面沙发上坐着一位戴着宽檐黑帽的高个男子。",
            },
            {
                "label": "交换条件",
                "body": "无面人交还企鹅护身符作为交换肖像的代价。",
            },
            {
                "label": "肖像困境",
                "body": "阅读助手因无面人的脸只有乳白色雾气，不知从何下笔。",
            },
        ],
    )
    issues = scan_summary_clarity(summary, raw_text=_FACELESS_RAW)
    leak = [issue for issue in issues if issue.code == "assistant_identity_leak"]
    assert {issue.field for issue in leak} >= {
        "sentences[0]",
        "bullets[0].body",
        "bullets[2].body",
    }
    assert all(issue.severity == "hard" for issue in leak)
    assert scan_summary_clarity(summary) == []


def test_clarity_scan_allows_narrator_for_first_person():
    summary = _summary(
        sentences=["本段讲述叙述者遭遇名为无面人的男子要求画肖像。"],
        bullets=[
            {
                "label": "遭遇无面人",
                "body": "叙述者醒来时，对面沙发上坐着一位戴着宽檐黑帽的高个男子。",
            },
            {
                "label": "交换条件",
                "body": "无面人交还企鹅护身符作为交换肖像的代价。",
            },
            {
                "label": "肖像困境",
                "body": "叙述者因无面人的脸只有乳白色雾气，不知从何下笔。",
            },
        ],
    )
    assert scan_summary_clarity(summary, raw_text=_FACELESS_RAW) == []


def test_clarity_scan_allows_assistant_when_in_source():
    summary = _summary(
        sentences=["阅读助手是书中出现的角色，并在本段醒来。"],
    )
    issues = scan_summary_clarity(
        summary,
        raw_text="名叫阅读助手的角色醒来，对面坐着一个男人。",
    )
    assert not any(issue.code == "assistant_identity_leak" for issue in issues)


class _ReviewRouter:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[str] = []

    async def complete(self, prompt, profile="summarize", json_mode=True, **kwargs):
        self.calls.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        if isinstance(self.response, str):
            return self.response
        return json.dumps(self.response, ensure_ascii=False)


@pytest.mark.asyncio
async def test_suspicious_summary_gets_model_review_and_merges_new_issue():
    summary = _summary(
        sentences=["本段交代主角离乡�赴考。"],
        notes=["这封来信让后续冲突变得难以理解。"],
    )
    router = _ReviewRouter(
        {
            "issues": [
                {
                    "field": "sentences[0]",
                    "problem": "包含乱码",
                    "snippet": "�",
                },
                {
                    "field": "notes[0]",
                    "problem": "指代不明，无法判断冲突对象",
                    "snippet": "这封来信",
                },
            ]
        }
    )
    result = await inspect_summary_quality(
        router,
        raw_text="主角收到陌生人的来信后离乡赴考。",
        summary=summary,
        review_prompt=load_prompts_config().segment_quality or "",
    )
    assert result.review_attempted is True
    assert len(result.issues) == 2
    assert len(router.calls) == 1


@pytest.mark.asyncio
async def test_soft_truncation_signal_is_confirmed_by_model():
    summary = _summary(
        sentences=["本段说明主角已经决定赴考，但是"],
        notes=["这个决定改变了后续安排。"],
    )
    router = _ReviewRouter(
        {
            "issues": [
                {
                    "field": "sentences[0]",
                    "problem": "句子在转折词处截断",
                    "snippet": "但是",
                },
                {
                    "field": "notes[0]",
                    "problem": "“这个决定”的内容不明确",
                    "snippet": "这个决定",
                },
            ]
        }
    )
    result = await inspect_summary_quality(
        router,
        raw_text="主角决定赴考，却没有说明随后的安排。",
        summary=summary,
        review_prompt=load_prompts_config().segment_quality or "",
    )
    assert result.review_attempted is True
    assert len(result.issues) == 2


@pytest.mark.asyncio
async def test_quality_review_accepts_fenced_json_and_deduplicates_same_site():
    summary = _summary(sentences=["本段交代主角离乡�赴考。"])
    router = _ReviewRouter(
        """```json
{"issues":[{"field":"sentences[0]","problem":"包含乱码","snippet":"�"}]}
```"""
    )
    result = await inspect_summary_quality(
        router,
        raw_text="主角离乡赴考。",
        summary=summary,
        review_prompt=load_prompts_config().segment_quality or "",
    )
    assert len(result.issues) == 1


@pytest.mark.asyncio
async def test_quality_review_failure_falls_back_to_local_result():
    summary = _summary(sentences=["本段交代主角离乡�赴考。"])
    result = await inspect_summary_quality(
        _ReviewRouter(RuntimeError("review unavailable")),
        raw_text="主角离乡赴考。",
        summary=summary,
        review_prompt=load_prompts_config().segment_quality or "",
    )
    assert result.review_attempted is True
    assert len(result.issues) == 1


def test_merge_does_not_count_same_location_twice():
    summary = _summary(sentences=["本段交代主角离乡�赴考。"])
    local = scan_summary_clarity(summary)
    model = [
        type(local[0])(
            field="sentences[0]",
            code="model_clarity",
            problem="包含乱码",
            snippet="�",
            severity="model",
            start=local[0].start,
        )
    ]
    assert len(merge_clarity_issues(local, model)) == 1


def test_job_timeout_budgets_generation_and_optional_review():
    from lumina_core import config

    timeout = summarize_job_timeout_seconds(_ReviewRouter({"issues": []}))
    assert timeout == config.SUMMARY_SEGMENT_TIMEOUT_SECONDS * config.MAX_SUMMARY_RETRIES * 2


@pytest.mark.asyncio
async def test_full_summary_retries_with_specific_quality_feedback():
    bad = _summary(
        sentences=["本段交代主角离乡�赴考。"],
        notes=["来信还有一处�无法辨认。"],
    ).model_dump()
    good = _summary().model_dump()

    class RetryRouter:
        def __init__(self) -> None:
            self.responses = [bad, good]
            self.prompts: list[str] = []

        async def complete(self, prompt, profile="summarize", json_mode=True, **kwargs):
            self.prompts.append(prompt)
            return json.dumps(self.responses.pop(0), ensure_ascii=False)

    router = RetryRouter()
    result = await summarize_segment(
        router,
        raw_text="主角收到来信后离乡赴考。",
        anchor_label="§第一章 · 段 1",
        max_retries=2,
    )
    assert result.llm_attempts == 2
    assert "上次摘要未通过质量检查" in router.prompts[1]
    assert "Unicode 乱码替换字符" in router.prompts[1]


@pytest.mark.asyncio
async def test_ollama_minimal_summary_uses_specific_quality_feedback():
    bad = _summary(sentences=["本段交代主角离乡�赴考。"]).model_dump(
        exclude={"label", "anchor", "notes"}
    )
    bad["bullets"][0]["body"] += " 来信中还有一处�无法辨认。"
    good = _summary().model_dump(exclude={"label", "anchor", "notes"})

    class RetryOllamaRouter(ProfileModelRouter):
        def __init__(self) -> None:
            super().__init__(
                ModelsConfig(
                    resources=[
                        ModelResource(
                            id="ollama",
                            provider="ollama",
                            base_url="http://127.0.0.1:11434",
                            model="qwen3.5:4b",
                        )
                    ],
                    summarize=ProfileRoute(priority=["ollama"]),
                )
            )
            self.responses = [bad, good]
            self.prompts: list[str] = []

        async def complete(self, prompt, profile="summarize", json_mode=True, **kwargs):
            self.prompts.append(prompt)
            return json.dumps(self.responses.pop(0), ensure_ascii=False)

    router = RetryOllamaRouter()
    result = await summarize_segment(
        router,
        raw_text="主角收到来信后离乡赴考。",
        anchor_label="§第一章 · 段 1",
        max_retries=2,
    )
    assert result.llm_attempts == 2
    assert "上次摘要未通过质量检查" in router.prompts[1]
    assert "上次输出不是合法 JSON" not in router.prompts[1]
