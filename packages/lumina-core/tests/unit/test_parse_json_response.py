"""parse_json_response LLM JSON repair tests."""

from __future__ import annotations

from lumina_core.models.router import parse_json_response

# Real malformed output from live test (missing comma + split objects)
LIVE_MALFORMED = (
    '{"sentences": ["主角于集市听闻新政后心绪起伏波澜。", "众人对科举变革及学术之争各执一词难达成一致。", '
    '"士子夜观月、访商队来信，皆感叹时局动荡民生多艰。"], "bullets": ["新政：集市传闻引发心中波澜...激越", '
    '"边关：商队诉说战事民生艰难", "故乡：夜读月色勾起过往旧景，" "学术：义理考据之争备受关注"]}, '
    '{"label": "# 章节·1：新政与风云变幻 · 情节推进 #段 1", "anchor":"§第一章 · 段"}'
)


def test_parse_live_malformed_summary_json():
    data = parse_json_response(LIVE_MALFORMED)
    assert len(data["sentences"]) == 3
    assert len(data["bullets"]) == 4
    assert data["bullets"][-2] == "故乡：夜读月色勾起过往旧景，"
    assert data["bullets"][-1] == "学术：义理考据之争备受关注"
    assert "label" in data
    assert data["anchor"] == "§第一章 · 段"


def test_repair_adjacent_strings_in_array():
    data = parse_json_response('{"bullets": ["a" "b", "c"]}')
    assert data["bullets"] == ["a", "b", "c"]


def test_parse_valid_summary_fixture(llm_fixtures_dir):
    raw = (llm_fixtures_dir / "summary_segment0.json").read_text(encoding="utf-8")
    data = parse_json_response(raw)
    assert len(data["sentences"]) == 3
    assert data["label"] == "引子：主角出身寒门"


def test_parse_json_with_markdown_fence():
    raw = """```json
{"sentences": ["一句。"], "bullets": ["a", "b", "c"], "label": "标签", "anchor": "§段 1"}
```"""
    data = parse_json_response(raw)
    assert data["label"] == "标签"


def test_parse_json_with_trailing_prose():
    raw = '{"sentences": ["一句。"], "bullets": ["a", "b", "c"], "label": "标签", "anchor": "§段 1"}\n\n以上是摘要。'
    data = parse_json_response(raw)
    assert data["label"] == "标签"


def test_merge_split_objects():
    data = parse_json_response('{"a": 1}, {"b": 2}')
    assert data == {"a": 1, "b": 2}


CLASSICAL_MALFORMED = (
    '{"sentences":["本段通过大量重复的古代儒家语录展示文本结构特征"],'
    '"bullets":[["章节名：学而","核心句：学而不厌、诲人不倦","仁之解：克己复礼"],'
    '"锚点":"§第一章 · 段落 N"},{"label":"《论语》语录重复测试样本"}]'
)


def test_parse_classical_malformed_summary_json():
    data = parse_json_response(CLASSICAL_MALFORMED)
    assert data["sentences"] == ["本段通过大量重复的古代儒家语录展示文本结构特征"]
    assert len(data["bullets"]) == 3
    assert data["anchor"] == "§第一章 · 段落 N"
    assert data["label"] == "《论语》语录重复测试样本"


# Live failure: bullet object closed with ] before top-level key (chunk_classical)
CLASSICAL_BULLET_BRACKET = (
    '{"sentences":["本章以重复句式呈现孔子\'学而不厌\'与弟子问仁的对话"],'
    '"bullets":[{"label":"语录循环","body":"文本通过多次重复同一对问答，模拟课堂讲授场景，强调孔子的核心教诲。"},'
    '{"label":"循环结构","body":"文本以重复问答循环呈现，强调语录体特征，而非构建真实叙事结构。"],'
    '"follow_ups":["为何文本选择反复陈述同一核心命题？","这种循环式表达在儒家经典中是否有特殊文体功能？"],'
    '"label":"《学而》篇：语录与哲思的循环呈现","anchor":"§段 1"}'
)


def test_repair_bullet_object_closed_with_bracket_before_top_level_key():
    data = parse_json_response(CLASSICAL_BULLET_BRACKET)
    assert len(data["bullets"]) == 2
    assert data["bullets"][0]["label"] == "语录循环"
    assert data["bullets"][1]["label"] == "循环结构"
    assert data["label"] == "《学而》篇：语录与哲思的循环呈现"
    assert data["anchor"] == "§段 1"


CLASSICAL_BULLET_BRACKET_MID = (
    '{"sentences":["一句。"],'
    '"bullets":[{"label":"a","body":"第一条要点说明文字足够长以满足校验要求内容。"},'
    '{"label":"b","body":"第二条要点说明文字足够长以满足校验要求内容。"],'
    '{"label":"c","body":"第三条要点说明文字足够长以满足校验要求内容。"}],'
    '"label":"测试","anchor":"§段 1"}'
)


def test_repair_bullet_object_closed_with_bracket_before_next_bullet():
    data = parse_json_response(CLASSICAL_BULLET_BRACKET_MID)
    assert len(data["bullets"]) == 3
    assert data["bullets"][0]["label"] == "a"
    assert data["bullets"][1]["label"] == "b"
    assert data["bullets"][2]["label"] == "c"


# Live failure: curly quotes in body + missing body open quote + bullet closed with ]
CLASSICAL_UNESCAPED_QUOTES = (
    '{"sentences":["本章通过重复孔子的教诲与弟子的提问，构建了经典的对话范式。",'
    '"文本在‘学而不厌’与‘克己复礼’两个核心命题间往复循环，强化儒家思想的权威性。"],'
    '"bullets":[{"label":"论语名句","body":“子曰”频繁出现，确立了孔子作为绝对权威的地位，其话语成为本章唯一的实质性内容来源。"},'
    '{"label":"重复修辞","body":两段对话（学而不厌与克己复礼）被机械复制 16 次，形成强烈的节奏感以模拟诵读或背诵场景。"],'
    '"notes":["本段实为文本合成测试样例，非完整文学段落；缺乏具体情境、人物背景及情节发展。"], '
    '"follow_ups":["为何在单一对话基础上进行如此大规模的重复处理？","这种结构化复制旨在探讨何种阅读体验？"],'
    '"label":"论语名句的循环复现","anchor":"§第一章 · 段 N"}'
)


def test_repair_unescaped_quotes_and_merged_bullet_fields():
    data = parse_json_response(CLASSICAL_UNESCAPED_QUOTES)
    assert len(data["sentences"]) == 2
    assert len(data["bullets"]) == 2
    assert data["bullets"][0]["label"] == "论语名句"
    assert "「子曰」" in data["bullets"][0]["body"]
    assert data["bullets"][1]["label"] == "重复修辞"
    assert data["label"] == "论语名句的循环复现"
    assert data["anchor"] == "§第一章 · 段 N"
