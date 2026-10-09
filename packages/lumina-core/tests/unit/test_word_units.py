"""Mixed-script reading length used by the chunker budget."""

from lumina_core.chunker.units import advance_units, count_units


def test_cjk_counts_per_character_and_skips_punctuation():
    assert count_units("你好，世界") == 4
    assert count_units("こんにちは") == 5
    assert count_units("안녕") == 2


def test_latin_and_other_spaced_scripts_count_per_word():
    assert count_units("Hello, world!") == 2
    assert count_units("Hello 世界") == 3
    assert count_units("it's") == 1
    assert count_units("Привет, мир!") == 2
    assert count_units("مرحبا بالعالم") == 2


def test_scriptio_continua_counts_per_code_point():
    thai = "สวัสดี"
    lao = "ສະບາຍດີ"
    assert count_units(thai) == len(thai)
    assert count_units(lao) == len(lao)
    assert count_units(thai) > 1


def test_advance_stops_on_a_word_boundary():
    text = "alpha beta gamma"
    assert advance_units(text, 0, 1) == len("alpha")
    assert advance_units(text, 0, 2) == len("alpha beta")
    assert text[: advance_units(text, 0, 2)].endswith("beta")
    assert advance_units("你好世界", 0, 2) == 2


def test_advance_caps_at_end_when_units_run_out():
    assert advance_units("one two", 0, 50) == len("one two")


def test_english_budget_packs_words_not_letters():
    from lumina_core.chunker.chunker import chunk_text
    from lumina_core.config import ChunkBudget

    text = " ".join(["alpha"] * 800)
    budget = ChunkBudget(target_chars=200, max_chars=300, min_chars=120)
    segments = chunk_text(text, budget=budget)
    assert len(segments) >= 2
    assert all(count_units(segment.raw_text) <= budget.max_chars for segment in segments)
    assert any(len(segment.raw_text) > budget.max_chars for segment in segments)
