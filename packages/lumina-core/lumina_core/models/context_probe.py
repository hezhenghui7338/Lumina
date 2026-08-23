"""Probe how much multi-segment context a model still *uses*, not just accepts."""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from lumina_core.config import ModelResource

CONTEXT_PROBE_LADDER: tuple[int, ...] = (1500, 2000, 2500, 3000, 3500, 4200, 4500)
CONTEXT_PROBE_RATIO = 0.8
CONTEXT_PROBE_CAP = 3500
CONTEXT_PROBE_FLOOR = 1500
CONTEXT_PROBE_TIMEOUT_SECONDS = 60.0
CONTEXT_PROBE_BACKGROUND_CHARS = 1600
CONTEXT_PROBE_SEGMENT_CHARS = 500

_FIRST_POOL = ("沈北川", "顾临川", "裴青禾", "江望舒", "陆衡秋")
_LAST_POOL = ("青瓷铃", "苔溪砚", "铜雀匣", "芦花笺", "乌木尺")

_TOPICS: tuple[str, ...] = (
    "河工记录：汛期水位上涨，沿岸村镇加高土堤，船家改走内汊。"
    "县衙派人巡堤，夜里灯火连成一线。有人主张明年改用石驳岸，也有人担心工钱不够。"
    "老堰工说上一回决口就在弯道，今年务必先清淤。",
    "市集见闻：粮行先开秤，布庄后挂牌，茶摊的炉子一整天不灭。"
    "外地客商只认成色，本地人更在意人情。午后雨点打在油纸伞上，货声反而更密。"
    "孩童追着糖人跑过巷口，把一盘算珠碰得乱响。",
    "观星札记：今夜云薄，箕宿西斜，测量的人把仪器支在城墙缺口。"
    "记录要写清方位和时刻，不能凭记忆补。有人争论岁差，有人只关心会不会下雨。"
    "风一紧，灯罩里的火苗就矮下去。",
    "庖厨备忘：新米下锅前要多淘两遍，火腿切薄片，笋只要嫩头。"
    "火候宁小勿大，汤面先撇浮沫。客人若来得晚，菜只能回锅，味道就钝了。"
    "案板上还留着未写完的菜单。",
    "营造手记：梁架要先放样，榫卯宁紧勿松，石础怕潮要垫瓦片。"
    "匠人午休在荫里抽烟，谈论哪座旧楼的斗拱走了形。雨季一到，未干的灰缝最容易空鼓。",
    "工头把尺寸又核对了一遍。",
    "田圃记：畦里的菜要间苗，虫口在叶背，不能只看表面。"
    "井水清晨凉，浇在根上比浇在叶上稳。邻田改种了别的作物，风一过花粉就混。"
    "篱笆缺了一截，黄狗常从那里钻。",
    "乐坊杂录：笛孔要烘干再上油，弦松了先别急着换。"
    "新来的学徒把节拍打在板上，老师只点头不说话。曲谱缺了两行，大家凭记忆往下接。"
    "窗外有人练嗓，和屋里的调对不上。",
    "狱讼摘要：两造各执一词，地契年号对不上，中人又说记不清。"
    "县衙要的是日期和见证人，不是形容词。有人把旧案卷翻出来，墨迹已糊成一片。"
    "廊下等待的人把鞋底的泥跺掉。",
    "航海私录：洋流比星图更先改方向，水手凭水色判断深浅。"
    "舱里潮湿，海图边缘卷起。有人看见岛影，有人说那是云。锚链响了一夜，谁也没睡实。",
    "淡水还够三天。",
    "书院日程：清晨背书，午前作文，晚饭后只准问疑。"
    "山长最厌空话，要求每句都落到文本上。有人把别人的评语抄进自己本子，被当众退回。"
    "院子里的槐花落了一层。",
    "边塞文书：草枯之后马更好控，烽火台缺油，夜里只能少点一盏。"
    "补给车陷在泥里，士兵把粮袋扛过坡。有人写信回家，墨未干就被风吹皱。"
    "远处鼓声不知是操练还是警报。",
    "医案残页：寒热往来三日，脉象不稳，药味要减不可加。"
    "病家求快，医者求稳。药渣倒在墙根，猫也不肯近。有人把旧方拿来对照，剂量对不上如今的秤。",
    "窗纸破了，风直灌进来。",
)

_BACKGROUND_UNIT = (
    "前序摘要：主人公已离开故乡，途中遇见旧识，双方对时局看法不一。"
    "章节里提到一次未完成的改革，以及几封没有寄出的信。这些线索只作背景，"
    "不能当作当前材料正在发生的事实来写。"
)

_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
_PROBE_CHARS_RE = re.compile(r"\[LUMINA_PROBE_CHARS=(\d+)\]")


class PinnedCompleter(Protocol):
    async def complete_pinned(
        self,
        resource: ModelResource,
        prompt: str,
        *,
        json_mode: bool = False,
        timeout: float | None = None,
        on_slot_acquired: Callable[[], Awaitable[None]] | None = None,
    ) -> str: ...


def recommend_chunk_target(max_ok_chars: int) -> int:
    """80% of the largest successful body, clamped to the product range."""
    if max_ok_chars <= 0:
        return CONTEXT_PROBE_FLOOR
    return max(
        CONTEXT_PROBE_FLOOR,
        min(CONTEXT_PROBE_CAP, int(max_ok_chars * CONTEXT_PROBE_RATIO)),
    )


def segment_count_for(total_chars: int) -> int:
    return max(2, (max(total_chars, 1) + CONTEXT_PROBE_SEGMENT_CHARS - 1) // CONTEXT_PROBE_SEGMENT_CHARS)


def _expand_topic(topic: str, chars: int) -> str:
    if chars <= 0:
        return ""
    block = topic.strip() or _TOPICS[0]
    repeats = (chars // len(block)) + 1
    return (block * repeats)[:chars]


def _pick_facts(rng: random.Random) -> tuple[str, str]:
    first = rng.choice(_FIRST_POOL)
    last = rng.choice(_LAST_POOL)
    return first, last


@dataclass(frozen=True)
class ProbePassage:
    first: str
    last: str
    segments: tuple[str, ...]

    @property
    def body(self) -> str:
        return "".join(self.segments)

    @property
    def segment_count(self) -> int:
        return len(self.segments)


def build_probe_passage(
    total_chars: int,
    *,
    rng: random.Random | None = None,
) -> ProbePassage:
    """Concatenate heterogeneous mini-segments totalling ``total_chars``."""
    rng = rng or random.Random()
    first, last = _pick_facts(rng)
    count = segment_count_for(total_chars)
    base, extra = divmod(max(total_chars, count), count)
    lengths = [base + (1 if i < extra else 0) for i in range(count)]
    first_sent = f"本段关键人物是{first}。"
    last_sent = f"本段关键物件是{last}。"
    parts: list[str] = []
    for index, length in enumerate(lengths):
        topic = _TOPICS[index % len(_TOPICS)]
        if index == 0:
            budget = max(0, length - len(first_sent))
            parts.append(_expand_topic(topic, budget) + first_sent)
        elif index == count - 1:
            budget = max(0, length - len(last_sent))
            parts.append(_expand_topic(topic, budget) + last_sent)
        else:
            decoy = _FIRST_POOL[(index + 1) % len(_FIRST_POOL)]
            if decoy == first:
                decoy = _FIRST_POOL[(index + 2) % len(_FIRST_POOL)]
            decoy_sent = f"本段提到过路人{decoy}，与首尾测验无关。"
            budget = max(0, length - len(decoy_sent))
            parts.append(_expand_topic(topic, budget) + decoy_sent)
    return ProbePassage(first=first, last=last, segments=tuple(parts))


def build_probe_prompt(passage: ProbePassage, *, total_chars: int) -> str:
    background = _expand_topic(_BACKGROUND_UNIT, CONTEXT_PROBE_BACKGROUND_CHARS)
    material = "\n\n".join(
        f"【第{index}段】\n{segment}"
        for index, segment in enumerate(passage.segments, start=1)
    )
    return (
        f"[LUMINA_PROBE_CHARS={total_chars}]\n"
        "以下是当前材料之前的摘要背景，仅用于消解人物与时间线，不是测验对象：\n"
        f"{background}\n\n"
        "以下材料由多段不同主题的文字依次拼接。后面的段落与前面同样重要，不能只看开头。\n\n"
        f"{material}\n\n"
        "请同时阅读第一段和最后一段。第一段写明了关键人物，最后一段写明了关键物件。"
        '只输出 JSON：{"first":"第一段的关键人物","last":"最后一段的关键物件"}。'
        "不要总结中间各段，不要编造。"
    )


def parse_probe_chars(prompt: str) -> int | None:
    match = _PROBE_CHARS_RE.search(prompt)
    if not match:
        return None
    return int(match.group(1))


def _norm_fact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip("「」\"'")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def facts_match(text: str, first: str, last: str) -> bool:
    """True only if the model identified both the first-segment and last-segment facts."""
    if not text or not first or not last:
        return False
    data = _extract_json_object(text)
    if data is not None:
        got_first = _norm_fact(data.get("first"))
        got_last = _norm_fact(data.get("last"))
        return got_first == first and got_last == last
    return False


def _error_message(exc: BaseException) -> str:
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    return text[:240]


@dataclass
class ContextProbeStatus:
    resource_id: str
    status: str = "idle"
    model: str = ""
    current_chars: int | None = None
    max_ok_chars: int | None = None
    recommended_chars: int | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    waiting_for_slot: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "status": self.status,
            "model": self.model,
            "current_chars": self.current_chars,
            "max_ok_chars": self.max_ok_chars,
            "recommended_chars": self.recommended_chars,
            "steps": list(self.steps),
            "message": self.message,
            "waiting_for_slot": self.waiting_for_slot,
        }


def idle_probe_status(resource_id: str, model: str = "") -> ContextProbeStatus:
    return ContextProbeStatus(resource_id=resource_id, status="idle", model=model)


def _finish_recommendation(status: ContextProbeStatus, *, weak: bool) -> None:
    max_ok = status.max_ok_chars or 0
    status.recommended_chars = recommend_chunk_target(max_ok)
    if weak or max_ok <= 0:
        status.message = (
            f"模型无法同时理解首段与末段（{CONTEXT_PROBE_LADDER[0]} 字档），"
            f"建议更换更大模型；已填入最低分段 {status.recommended_chars} 字"
        )
        return
    status.message = (
        f"实测后面内容仍被理解约 {max_ok} 字 · 建议分段 {status.recommended_chars} 字"
        f"（80%，上限 {CONTEXT_PROBE_CAP}）"
    )


async def _complete_or_cancel(
    coro: Awaitable[str],
    cancel_event: asyncio.Event,
) -> str | None:
    task = asyncio.create_task(coro)
    cancel_task = asyncio.create_task(cancel_event.wait())
    try:
        await asyncio.wait(
            {task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_event.is_set():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            return None
        return task.result()
    finally:
        if not cancel_task.done():
            cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_task
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def run_context_probe(
    *,
    router: PinnedCompleter,
    resource: ModelResource,
    status: ContextProbeStatus,
    cancel_event: asyncio.Event,
    ladder: Sequence[int] = CONTEXT_PROBE_LADDER,
    timeout: float = CONTEXT_PROBE_TIMEOUT_SECONDS,
) -> ContextProbeStatus:
    status.status = "running"
    status.model = resource.model
    status.current_chars = None
    status.max_ok_chars = None
    status.recommended_chars = None
    status.steps = []
    status.message = "正在测试后面的段是否仍被理解…"
    status.waiting_for_slot = False

    async def _on_slot() -> None:
        status.waiting_for_slot = False
        if status.current_chars:
            status.message = f"正在测 {status.current_chars} 字（须答对末段）…"

    try:
        for chars in ladder:
            if cancel_event.is_set():
                status.status = "cancelled"
                status.message = "已取消"
                return status

            status.current_chars = chars
            status.waiting_for_slot = True
            status.message = f"等待模型空闲…（接着测 {chars} 字）"
            passage = build_probe_passage(chars)
            prompt = build_probe_prompt(passage, total_chars=chars)
            try:
                text = await _complete_or_cancel(
                    router.complete_pinned(
                        resource,
                        prompt,
                        json_mode=True,
                        timeout=timeout,
                        on_slot_acquired=_on_slot,
                    ),
                    cancel_event,
                )
            except asyncio.CancelledError:
                status.status = "cancelled"
                status.message = "已取消"
                status.waiting_for_slot = False
                return status
            except Exception as exc:
                status.waiting_for_slot = False
                status.steps.append(
                    {"chars": chars, "ok": False, "message": _error_message(exc)}
                )
                break

            if text is None or cancel_event.is_set():
                status.status = "cancelled"
                status.message = "已取消"
                status.waiting_for_slot = False
                return status

            status.waiting_for_slot = False
            ok = facts_match(text, passage.first, passage.last)
            if ok:
                fail_reason = ""
            else:
                data = _extract_json_object(text) or {}
                got_last = _norm_fact(data.get("last"))
                if _norm_fact(data.get("first")) == passage.first and got_last != passage.last:
                    fail_reason = "末段事实未被理解（只处理了前面的段）"
                else:
                    fail_reason = "未能同时答对首段与末段事实"
            status.steps.append({"chars": chars, "ok": ok, "message": fail_reason})
            if not ok:
                break
            status.max_ok_chars = chars

        status.status = "done"
        status.waiting_for_slot = False
        status.current_chars = status.max_ok_chars
        _finish_recommendation(
            status,
            weak=not status.steps or not any(step.get("ok") for step in status.steps),
        )
        return status
    except asyncio.CancelledError:
        status.status = "cancelled"
        status.message = "已取消"
        status.waiting_for_slot = False
        return status
