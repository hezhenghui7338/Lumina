"""Ingest format tests."""

from pathlib import Path

import pytest

from lumina_core.ingest.loader import build_segments, detect_format, load_document


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("book.txt", "txt"),
        ("book.TEXT", "txt"),
        ("book.md", "txt"),
        ("book.markdown", "txt"),
        ("book.mdown", "txt"),
        ("book.mkd", "txt"),
        ("book.log", "txt"),
        ("book.html", "html"),
        ("book.htm", "html"),
        ("book.xhtml", "html"),
        ("book.rtf", "rtf"),
        ("book.docx", "docx"),
        ("book.odt", "odt"),
        ("book.fb2", "fb2"),
        ("book.mobi", "mobi"),
        ("book.azw", "mobi"),
        ("book.azw3", "mobi"),
        ("book.AZW3", "mobi"),
    ],
)
def test_detect_format(filename, expected):
    assert detect_format(Path(filename)) == expected


def test_detect_format_rejects_unsupported_file():
    with pytest.raises(ValueError, match="Unsupported format"):
        detect_format(Path("legacy.doc"))


def test_load_txt_roundtrip(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("第一章 测试\n\n段落内容。", encoding="utf-8")
    text, meta = load_document(p, "txt")
    assert "段落内容" in text
    assert meta == {}


def test_load_txt_gb18030_golden_pavilion(tmp_path):
    p = tmp_path / "金阁寺.txt"
    p.write_bytes("『金阁寺/作者:三岛由纪夫』\n正文。".encode("gb18030"))
    text, meta = load_document(p, "txt")
    assert "金阁寺" in text
    assert "三岛由纪夫" in text
    assert meta == {}


def _block_utf8_sig_codec(monkeypatch) -> None:
    """Simulate a frozen sidecar that does not ship encodings.utf_8_sig."""
    import codecs

    from lumina_core.ingest import text as text_mod

    real_try_decode = text_mod._try_decode
    real_read_text = Path.read_text
    real_lookup = codecs.lookup

    def try_decode(data: bytes, encoding: str) -> str:
        if encoding.lower().replace("_", "-") == "utf-8-sig":
            raise LookupError(f"unknown encoding: {encoding}")
        return real_try_decode(data, encoding)

    def read_text(self, encoding=None, errors=None, newline=None):
        if encoding and str(encoding).lower().replace("_", "-") == "utf-8-sig":
            raise LookupError("unknown encoding: utf-8-sig")
        return real_read_text(self, encoding=encoding, errors=errors, newline=newline)

    def lookup(name):
        if str(name).lower().replace("_", "-") == "utf-8-sig":
            raise LookupError(f"unknown encoding: {name}")
        return real_lookup(name)

    monkeypatch.setattr(text_mod, "_try_decode", try_decode)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(codecs, "lookup", lookup)


def test_decode_text_bytes_never_requests_utf8_sig():
    from lumina_core.ingest.text import _CANDIDATE_ENCODINGS

    assert "utf-8-sig" not in _CANDIDATE_ENCODINGS


def test_pyinstaller_spec_bundles_text_encodings():
    spec = Path(__file__).resolve().parents[2] / "lumina-core.spec"
    text = spec.read_text(encoding="utf-8")
    for name in (
        "encodings.utf_8_sig",
        "encodings.gb18030",
        "encodings.gbk",
        "encodings.cp936",
        "encodings.cp1252",
        "encodings.latin_1",
        "encodings.big5",
    ):
        assert name in text, f"{name} must be a PyInstaller hiddenimport"


def test_load_txt_gb18030_when_utf8_sig_codec_missing(tmp_path, monkeypatch):
    _block_utf8_sig_codec(monkeypatch)
    p = tmp_path / "金阁寺.txt"
    p.write_bytes("『金阁寺』第一章。".encode("gb18030"))
    text, _ = load_document(p, "txt")
    assert "金阁寺" in text


def test_load_html_bom_when_utf8_sig_codec_missing(tmp_path, monkeypatch):
    _block_utf8_sig_codec(monkeypatch)
    p = tmp_path / "bom.html"
    html = (
        "<html><head><title>BOM 书</title></head>"
        "<body><h1>第一章</h1><p>正文。</p></body></html>"
    )
    p.write_bytes(b"\xef\xbb\xbf" + html.encode("utf-8"))
    text, meta = load_document(p, "html")
    assert "正文" in text
    assert meta["title"] == "BOM 书"
    assert not text.startswith("\ufeff")


def test_load_txt_strips_utf8_bom(tmp_path):
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbf" + "第一章\n".encode("utf-8"))
    text, _ = load_document(p, "txt")
    assert text.startswith("第一章")


def _gbk_prose() -> str:
    return "　　双方继续对峙，刘长无奈的放开了系带。" * 8


def test_decode_raw_gbk_bytes_to_han():
    from lumina_core.ingest.text import decode_text_bytes

    original = _gbk_prose()
    assert "双方继续对峙" in decode_text_bytes(original.encode("gbk"))


def test_decode_utf8_stored_gbk_latin1_mojibake():
    from lumina_core.ingest.text import decode_text_bytes

    original = _gbk_prose()
    mojibake = original.encode("gbk").decode("latin-1")
    recovered = decode_text_bytes(mojibake.encode("utf-8"))
    assert "双方继续对峙" in recovered
    assert "¡¡¡¡" not in recovered


def test_decode_utf8_chinese_not_rewritten():
    from lumina_core.ingest.text import decode_text_bytes

    original = _gbk_prose()
    assert decode_text_bytes(original.encode("utf-8")) == original


def test_load_txt_recovers_utf8_mojibake_file(tmp_path):
    original = _gbk_prose()
    p = tmp_path / "mojibake.txt"
    p.write_bytes(original.encode("gbk").decode("latin-1").encode("utf-8"))
    text, _ = load_document(p, "txt")
    assert "双方继续对峙" in text


def test_detect_plan_utf8_chinese_not_mojibake():
    from lumina_core.ingest.text import detect_encoding_plan

    plan = detect_encoding_plan(_gbk_prose().encode("utf-8"))
    assert plan.encoding == "utf-8"
    assert plan.recover_gbk_mojibake is False


def test_detect_plan_gbk_bytes():
    from lumina_core.ingest.text import detect_encoding_plan

    plan = detect_encoding_plan(_gbk_prose().encode("gbk"))
    assert plan.encoding == "gb18030"
    assert plan.recover_gbk_mojibake is False


def test_detect_plan_utf8_mojibake_recovers():
    from lumina_core.ingest.text import detect_encoding_plan

    original = _gbk_prose()
    data = original.encode("gbk").decode("latin-1").encode("utf-8")
    plan = detect_encoding_plan(data)
    assert plan.recover_gbk_mojibake is True


def test_detect_plan_utf8_not_rejected_when_sample_cuts_multibyte():
    from lumina_core.ingest.text import _SAMPLE_BYTES, detect_encoding_plan

    payload = ("学而时习之，不亦说乎。" * 40).encode("utf-8")
    data = b"A" * (_SAMPLE_BYTES - 2) + payload
    with pytest.raises(UnicodeDecodeError):
        data[:_SAMPLE_BYTES].decode("utf-8")
    plan = detect_encoding_plan(data)
    assert plan.encoding == "utf-8"
    assert plan.recover_gbk_mojibake is False


def test_detect_plan_utf8_fixture_books_larger_than_sample():
    from lumina_core.ingest.text import detect_encoding_plan

    books = Path(__file__).resolve().parents[1] / "fixtures" / "books"
    for name in ("chunk_classical.txt", "chunk_long_novel.txt"):
        raw = (books / name).read_bytes()
        plan = detect_encoding_plan(raw)
        assert plan.encoding == "utf-8", name
        assert plan.recover_gbk_mojibake is False, name


def test_load_txt_classical_fixture_roundtrip():
    books = Path(__file__).resolve().parents[1] / "fixtures" / "books"
    text, _ = load_document(books / "chunk_classical.txt", "txt")
    assert "学而" in text


def _gbk_ebook_with_binary_junk() -> bytes:
    """GBK novel bytes plus an illegal lead/trail pair, as in pirated TXT dumps."""
    prose = "一九六五年八月九日，照顾二百万人民生计的重担突然落在李光耀肩上。\n" * 80
    body = prose.encode("gbk")
    junk = b"$ \x00  \x00\x00\x00\x00   \x00\x00\x00\xd0\x14\xc0\x85H@\"\x06\x0c\x00"
    return body + junk + body


def test_detect_plan_gbk_with_embedded_binary_junk():
    from lumina_core.ingest.text import _SAMPLE_BYTES, detect_encoding_plan

    data = _gbk_ebook_with_binary_junk()
    with pytest.raises(UnicodeDecodeError):
        data[:_SAMPLE_BYTES].decode("gb18030")
    plan = detect_encoding_plan(data)
    assert plan.encoding == "gb18030"
    assert plan.recover_gbk_mojibake is False


def test_load_txt_gbk_with_embedded_binary_junk(tmp_path):
    p = tmp_path / "lee.txt"
    p.write_bytes(_gbk_ebook_with_binary_junk())
    text, _ = load_document(p, "txt")
    assert text.count("李光耀") >= 2
    assert "生计" in text
    assert "\x00" not in text


def test_decode_text_bytes_gbk_embedded_binary_strips_nuls():
    from lumina_core.ingest.text import decode_text_bytes

    text = decode_text_bytes(_gbk_ebook_with_binary_junk())
    assert "李光耀" in text
    assert "\x00" not in text


def test_detect_plan_utf8_with_illegal_byte_in_sample():
    from lumina_core.ingest.text import _SAMPLE_BYTES, detect_encoding_plan

    payload = ("学而时习之，不亦说乎。" * 3000).encode("utf-8")
    data = bytearray(payload[:_SAMPLE_BYTES])
    data[40_000] = 0xFF
    raw = bytes(data)
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    plan = detect_encoding_plan(raw)
    assert plan.encoding == "utf-8"
    assert plan.recover_gbk_mojibake is False


def test_detect_plan_rejects_binary_without_cjk_prose():
    from lumina_core.ingest.text import UNRECOGNIZED_ENCODING, detect_encoding_plan

    data = b"\xd0\x14\x00\xff" * 16_384
    with pytest.raises(ValueError, match=UNRECOGNIZED_ENCODING):
        detect_encoding_plan(data)


def test_pyinstaller_spec_bundles_charset_normalizer():
    spec = Path(__file__).resolve().parents[2] / "lumina-core.spec"
    text = spec.read_text(encoding="utf-8")
    assert "charset_normalizer" in text


def test_load_html_preserves_headings_and_metadata(tmp_path):
    p = tmp_path / "sample.html"
    p.write_text(
        """
        <html><head><title>HTML 测试书</title><meta name="author" content="测试作者"></head>
        <body><h1>第一章</h1><p>正文段落。</p><script>不要收录</script></body></html>
        """,
        encoding="utf-8",
    )
    text, meta = load_document(p, "html")
    assert "## [§第一章]" in text
    assert "正文段落" in text
    assert "不要收录" not in text
    assert meta == {"title": "HTML 测试书", "author": "测试作者"}


def test_load_html_strips_source_section_sign_from_heading(tmp_path):
    p = tmp_path / "section.html"
    p.write_text(
        "<html><body><h1>§ 第一章</h1><p>正文段落。</p></body></html>",
        encoding="utf-8",
    )
    text, _ = load_document(p, "html")
    assert "## [§第一章]" in text
    assert "## [§§" not in text


def test_load_html_nests_h2_as_section_not_chapter(tmp_path):
    p = tmp_path / "nested.html"
    p.write_text(
        """
        <html><head><title>分层</title></head>
        <body>
          <h1>第一章</h1><p>章正文。</p>
          <h2>第一节</h2><p>节正文。</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    text, _ = load_document(p, "html")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    assert "## [§第一章]" in lines
    assert "### [§第一节]" in lines
    assert "## [§第一节]" not in lines


def test_load_rtf_text_and_metadata(tmp_path):
    p = tmp_path / "sample.rtf"
    p.write_text(
        r"{\rtf1\ansi{\info{\title RTF Test}{\author Alice}}"
        r"\b Chapter One\b0\par Body text.}",
        encoding="latin-1",
    )
    text, meta = load_document(p, "rtf")
    assert "Chapter One" in text
    assert "Body text" in text
    assert meta == {"title": "RTF Test", "author": "Alice"}


def test_load_docx_preserves_headings_tables_and_metadata(tmp_path):
    docx = pytest.importorskip("docx")
    p = tmp_path / "sample.docx"
    document = docx.Document()
    document.core_properties.title = "DOCX 测试书"
    document.core_properties.author = "测试作者"
    document.add_heading("第一章", level=1)
    document.add_paragraph("正文段落。")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "甲"
    table.cell(0, 1).text = "乙"
    document.save(p)

    text, meta = load_document(p, "docx")
    assert "## [§第一章]" in text
    assert "正文段落" in text
    assert "甲 | 乙" in text
    assert meta == {"title": "DOCX 测试书", "author": "测试作者"}


def test_load_odt_preserves_headings_and_metadata(tmp_path):
    pytest.importorskip("odf")
    from odf import dc, text
    from odf.opendocument import OpenDocumentText

    p = tmp_path / "sample.odt"
    document = OpenDocumentText()
    document.meta.addElement(dc.Title(text="ODT 测试书"))
    document.meta.addElement(dc.Creator(text="测试作者"))
    document.text.addElement(text.H(outlinelevel=1, text="第一章"))
    document.text.addElement(text.P(text="正文段落。"))
    document.save(str(p))

    content, metadata = load_document(p, "odt")
    assert "## [§第一章]" in content
    assert "正文段落" in content
    assert metadata == {"title": "ODT 测试书", "author": "测试作者"}


def test_load_fb2_preserves_sections_and_metadata(tmp_path):
    p = tmp_path / "sample.fb2"
    p.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
        <FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
          <description><title-info><book-title>FB2 测试书</book-title>
            <author><first-name>小</first-name><last-name>明</last-name></author>
          </title-info></description>
          <body><section><title><p>第一章</p></title><p>正文段落。</p></section></body>
        </FictionBook>""",
        encoding="utf-8",
    )
    text, meta = load_document(p, "fb2")
    assert "## [§第一章]" in text
    assert "正文段落" in text
    assert meta == {"title": "FB2 测试书", "author": "小 明"}


def test_load_fb2_utf8_sig_declaration_when_codec_missing(tmp_path, monkeypatch):
    _block_utf8_sig_codec(monkeypatch)
    p = tmp_path / "sig.fb2"
    p.write_text(
        """<?xml version="1.0" encoding="utf-8-sig"?>
        <FictionBook>
          <description><title-info><book-title>声明测试</book-title>
          </title-info></description>
          <body><section><title><p>序</p></title><p>正文。</p></section></body>
        </FictionBook>""",
        encoding="utf-8",
    )
    text, meta = load_document(p, "fb2")
    assert "正文" in text
    assert meta["title"] == "声明测试"


@pytest.mark.parametrize(
    ("filename", "fmt", "content", "message"),
    [
        ("empty.html", "html", "<html><script>empty</script></html>", "no readable text"),
        ("broken.rtf", "rtf", "not rtf", "Invalid RTF"),
        ("broken.docx", "docx", "not a zip", "Invalid or encrypted DOCX"),
        ("broken.odt", "odt", "not a zip", "Invalid or encrypted ODT"),
        ("broken.fb2", "fb2", "<broken", "Invalid FB2"),
    ],
)
def test_structured_formats_report_stable_errors(tmp_path, filename, fmt, content, message):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_document(p, fmt)


def test_build_segments_from_txt():
    text = "第一章 开篇\n\n" + ("内容。" * 500)
    segs = build_segments("book-1", text)
    assert len(segs) >= 1
    assert segs[0]["book_id"] == "book-1"
    assert segs[0]["char_count"] == len(segs[0]["raw_text"])
    assert sum(s["char_count"] for s in segs) == len(text.strip())


@pytest.mark.skipif(
    not Path("/System/Library/CoreServices/").exists(),
    reason="PDF fixture generation optional",
)
def test_load_pdf_if_pypdf_available(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    from lumina_core import config
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult

    p = tmp_path / "mini.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Mini PDF"})
    with p.open("wb") as f:
        writer.write(f)

    # Blank page has no text layer — mock OCR so test does not need RapidOCR deps
    monkeypatch.setattr(config, "OCR_ENABLED", True)

    def _fake(_path, **_kwargs):
        return OcrDocumentResult(
            text="## [p.1]\nocr-text",
            pages=[OcrPageResult(1, "ocr-text", 0.9, False)],
            avg_confidence=0.9,
        )

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", _fake)
    text, meta = load_document(p, "pdf")
    assert meta.get("title") == "Mini PDF"
    assert "ocr-text" in text
    assert meta.get("ocr_used") is True
    assert meta.get("ocr_pages") == 1


def test_load_pdf_triggers_ocr_when_low_coverage(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    from lumina_core import config
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult

    p = tmp_path / "sparse.pdf"
    writer = PdfWriter()
    for _ in range(10):
        writer.add_blank_page(width=200, height=200)
    with p.open("wb") as f:
        writer.write(f)

    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(config, "OCR_PDF_TEXT_RATIO", 0.15)

    calls: list[dict] = []

    def _fake(_path, **kwargs):
        calls.append(kwargs)
        return OcrDocumentResult(
            text="## [p.1]\nocr-text",
            pages=[OcrPageResult(1, "ocr-text", 0.9, False)],
            avg_confidence=0.9,
        )

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", _fake)
    text, meta = load_document(p, "pdf")
    assert calls, "expected OCR for zero-text PDF"
    assert "ocr-text" in text
    assert meta.get("ocr_used") is True


def test_load_pdf_partial_ocr_for_mixed_pages(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    fitz = pytest.importorskip("fitz")

    from lumina_core import config
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult

    p = tmp_path / "mixed.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "text layer page")
    for _ in range(9):
        doc.new_page()
    doc.save(str(p))
    doc.close()

    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(config, "OCR_PDF_TEXT_RATIO", 0.15)

    def _fake(_path, **kwargs):
        page_nums = kwargs.get("page_nums")
        assert page_nums == list(range(2, 11))
        return OcrDocumentResult(
            text="## [p.2]\nscan-page",
            pages=[OcrPageResult(2, "scan-page", 0.9, False)],
            avg_confidence=0.9,
        )

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", _fake)
    text, meta = load_document(p, "pdf")
    assert "text layer page" in text
    assert "scan-page" in text
    assert meta.get("ocr_partial") is True


def test_probe_page_indices_caps_large_pdfs():
    from lumina_core.ingest.pdf import _PDF_PROBE_MAX, _probe_page_indices

    assert _probe_page_indices(10) == list(range(1, 11))
    probed = _probe_page_indices(213)
    assert probed[0] == 1
    assert probed[-1] == 213
    assert len(probed) <= _PDF_PROBE_MAX


def test_load_pdf_probe_skips_remaining_extract_on_scanned_doc(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    from lumina_core import config
    from lumina_core.ingest import pdf as pdf_mod
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult

    p = tmp_path / "scanned-long.pdf"
    writer = PdfWriter()
    for _ in range(20):
        writer.add_blank_page(width=200, height=200)
    with p.open("wb") as f:
        writer.write(f)

    monkeypatch.setattr(config, "OCR_ENABLED", True)
    calls = {"n": 0}
    original = pdf_mod._page_text

    def counted(page):
        calls["n"] += 1
        return original(page)

    monkeypatch.setattr(pdf_mod, "_page_text", counted)

    def _fake(_path, **_kwargs):
        return OcrDocumentResult(
            text="## [p.1]\nocr-text",
            pages=[OcrPageResult(1, "ocr-text", 0.9, False)],
            avg_confidence=0.9,
        )

    monkeypatch.setattr(pdf_mod, "ocr_pdf", _fake)
    text, meta = load_document(p, "pdf")
    assert calls["n"] <= pdf_mod._PDF_PROBE_MAX
    assert calls["n"] < 20
    assert meta.get("text_layer_probed") is True
    assert "ocr-text" in text


def test_load_pdf_cancel_during_probe(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    import threading

    from pypdf import PdfWriter

    from lumina_core.ingest.pdf import load_pdf
    from lumina_core.ingest.progress import DocumentLoadCancelled

    p = tmp_path / "cancel.pdf"
    writer = PdfWriter()
    for _ in range(8):
        writer.add_blank_page(width=200, height=200)
    with p.open("wb") as f:
        writer.write(f)

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DocumentLoadCancelled):
        load_pdf(p, cancel_event=cancel)


def test_load_pdf_emits_progress_before_ocr(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    from lumina_core import config
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult
    from lumina_core.ingest.pdf import load_pdf

    p = tmp_path / "progress.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with p.open("wb") as f:
        writer.write(f)

    monkeypatch.setattr(config, "OCR_ENABLED", True)
    messages: list[str] = []

    def on_progress(_page, _total, message):
        messages.append(message)

    monkeypatch.setattr(
        "lumina_core.ingest.pdf.ocr_pdf",
        lambda *_a, **_k: OcrDocumentResult(
            text="## [p.1]\nocr-text",
            pages=[OcrPageResult(1, "ocr-text", 0.9, False)],
            avg_confidence=0.9,
        ),
    )
    load_pdf(p, on_progress=on_progress)
    assert any("打开 PDF" in m or "文本层" in m for m in messages)


# pypdf extract of EasyRL_v1.0.6.pdf p.2 (FandolSong Identity-H, no ToUnicode)
_EASYRL_PYPDF_PAGE2 = (
    "భ\u0ffd\n\u0ce5\nႨທAtari\nေv a \u09d9॓\nದ\nb\n\u0d50Ⴈඪૼ\n"
    "•ֻ4ֻ֞11 ᅣູ࿐༝vĠ\n•ֻ1ֻބ2ऌေvটĠ\n•ֻ3ֻބ12ऌ࿐༝vটb\n"
    "߶\nщ\u0ebeğQi WangaYiyuan YangaJi Jiang\n"
    "ᇁ྆\n྆ Sm1lesaLSGOMYPϺᇹაᆦӻb\n"
    "Սo࿐༝ೆoEasy-RLੀಕp\nDatawhale\nህᇿႿ AIषჷቆᆮ\n"
    "ϱಃലૼ\nЧቔ\u0bd6ҐႨཚඇ\u0b00-അြྟ\u0d50Ⴈ-ཚ 4.0ྸॖླྀၰྛྸॖb"
)
_EASYRL_FITZ_PAGE2 = (
    "前言\n李宏毅老师的《深度强化学习》是强化学习领域经典的中文视频之一。"
    "李老师幽默风趣的上课风格让晦涩难懂的强化学习理论变得轻松易懂，"
    "他会通过很多有趣的例子来讲解强化学习理论。比如老师经常会用玩Atari"
    "游戏的例子来讲解强化学习算法。"
)


def test_text_layer_garbled_identity_h_sample():
    from lumina_core.ingest.pdf import text_layer_garbled

    assert text_layer_garbled(_EASYRL_PYPDF_PAGE2)
    assert not text_layer_garbled(_EASYRL_FITZ_PAGE2)
    assert not text_layer_garbled("Chapter 1 Reinforcement Learning\n" * 8)
    assert text_layer_garbled("body " * 20 + "(cid:1234) more")


def test_load_pdf_prefers_pymupdf_cjk_text_layer(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")

    p = tmp_path / "easyrl-like.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "强化学习教程 EasyRL", fontname="china-s", fontsize=18)
    page.insert_text((72, 120), "智能体在环境里面获取某个状态", fontname="china-s", fontsize=12)
    doc.save(str(p))
    doc.close()

    monkeypatch.setattr(
        "lumina_core.ingest.pdf.ocr_pdf",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("usable text layer must not OCR")
        ),
    )
    text, meta = load_document(p, "pdf")
    assert "强化学习" in text
    assert "智能体" in text
    assert meta.get("pdf_extractor") == "pymupdf"
    assert meta.get("ocr_used") is not True


def test_load_pdf_garbled_pypdf_layer_triggers_ocr(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    fitz = pytest.importorskip("fitz")

    from lumina_core import config
    from lumina_core.ingest import pdf as pdf_mod
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult

    p = tmp_path / "cid.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "placeholder text that pypdf would see as a layer")
    doc.save(str(p))
    doc.close()

    monkeypatch.setattr(pdf_mod, "_open_fitz", lambda _path: None)
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(pdf_mod, "_page_text", lambda _page: _EASYRL_PYPDF_PAGE2)

    def _fake(_path, **_kwargs):
        return OcrDocumentResult(
            text="## [p.1]\n强化学习概述",
            pages=[OcrPageResult(1, "强化学习概述", 0.9, False)],
            avg_confidence=0.9,
        )

    monkeypatch.setattr(pdf_mod, "ocr_pdf", _fake)
    text, meta = load_document(p, "pdf")
    assert "强化学习概述" in text
    assert meta.get("ocr_used") is True
    assert meta.get("pdf_extractor") == "pypdf"
    assert meta.get("text_layer_garbled_pages") == [1]


def _write_epub_with_id_href_mismatch(path: Path) -> None:
    """Typical EPUB: spine idref != file href (e.g. c0_gu_wang_yan vs c0_gu_wang_yan.xhtml)."""
    ebooklib = pytest.importorskip("ebooklib")
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("lumina-epub-test")
    book.set_title("姑妄言")
    book.add_author("曹去晶")

    chapter = epub.EpubHtml(
        title="卷一",
        file_name="c0_gu_wang_yan.xhtml",
        uid="c0_gu_wang_yan",
        lang="zh",
    )
    chapter.set_content("<html><body><h1>卷一</h1><p>正文段落甲乙丙。</p></body></html>")
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [chapter]
    epub.write_epub(str(path), book)

    loaded = epub.read_epub(str(path))
    idref = loaded.spine[0][0]
    assert loaded.get_item_with_href(idref) is None
    assert loaded.get_item_with_id(idref) is not None
    assert loaded.get_item_with_id(idref).get_type() == ebooklib.ITEM_DOCUMENT


def test_load_epub_uses_spine_idref_not_href(tmp_path):
    p = tmp_path / "gu-wang-yan.epub"
    _write_epub_with_id_href_mismatch(p)
    text, meta = load_document(p, "epub")
    assert meta.get("title") == "姑妄言"
    assert meta.get("author") == "曹去晶"
    assert "正文段落甲乙丙" in text
    assert "§" in text


def test_load_epub_falls_back_when_spine_empty(tmp_path, monkeypatch):
    p = tmp_path / "no-spine.epub"
    _write_epub_with_id_href_mismatch(p)
    from ebooklib import epub as ebooklib_epub
    from lumina_core.ingest.epub import load_epub

    original_read = ebooklib_epub.read_epub

    def _read_empty_spine(path, *args, **kwargs):
        book = original_read(path, *args, **kwargs)
        book.spine = []
        return book

    monkeypatch.setattr(ebooklib_epub, "read_epub", _read_empty_spine)
    text, _meta = load_epub(p)
    assert "正文段落甲乙丙" in text


def test_load_epub_landmarks_set_structure_roles_not_raw_text(tmp_path):
    ebooklib = pytest.importorskip("ebooklib")
    from ebooklib import epub

    from lumina_core.ingest.epub import load_epub

    book = epub.EpubBook()
    book.set_identifier("lumina-landmark")
    book.set_title("带序的书")
    book.add_author("测试")

    preface = epub.EpubHtml(title="序", file_name="preface.xhtml", uid="preface", lang="zh")
    preface.set_content("<html><body><h1>序</h1><p>这是独立的序言文字。</p></body></html>")
    chapter = epub.EpubHtml(title="第一章", file_name="ch1.xhtml", uid="ch1", lang="zh")
    chapter.set_content("<html><body><h1>第一章</h1><p>这是正文第一章。</p></body></html>")
    book.add_item(preface)
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [preface, chapter]
    book.guide = [
        {"type": "preface", "title": "序", "href": "preface.xhtml"},
        {"type": "text", "title": "第一章", "href": "ch1.xhtml"},
    ]
    path = tmp_path / "with-preface.epub"
    epub.write_epub(str(path), book)

    text, meta = load_epub(path)
    assert "role=" not in text
    assert "这是独立的序言文字" in text
    assert "这是正文第一章" in text
    roles = meta.get("structure_roles") or []
    assert any(item["role"] == "preface" and "序" in item["title"] for item in roles)
    assert any(item["role"] == "bodymatter" for item in roles)


def test_load_epub_strips_source_section_sign_from_title(tmp_path):
    ebooklib = pytest.importorskip("ebooklib")
    from ebooklib import epub

    from lumina_core.ingest.epub import load_epub

    book = epub.EpubBook()
    book.set_identifier("lumina-section-sign")
    book.set_title("带节号的书")
    book.add_author("测试")
    chapter = epub.EpubHtml(
        title="§ 卷一",
        file_name="c1.xhtml",
        uid="c1",
        lang="zh",
    )
    chapter.set_content("<html><body><h1>§ 卷一</h1><p>正文段落甲乙丙。</p></body></html>")
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [chapter]
    path = tmp_path / "section-sign.epub"
    epub.write_epub(str(path), book)

    text, _meta = load_epub(path)
    assert "正文段落甲乙丙" in text
    assert "## [§卷一]" in text
    assert "## [§§" not in text


def test_load_azw3_extracts_via_mobi_epub(tmp_path, monkeypatch):
    pytest.importorskip("ebooklib")
    mobi = pytest.importorskip("mobi")

    extract_dir = tmp_path / "mobi-extract"
    extract_dir.mkdir()
    epub_path = extract_dir / "book.epub"
    _write_epub_with_id_href_mismatch(epub_path)

    azw3 = tmp_path / "kindle-book.azw3"
    azw3.write_bytes(b"BOOKMOBI-fake")

    monkeypatch.setattr(mobi, "extract", lambda _path: (str(extract_dir), str(epub_path)))

    text, _meta = load_document(azw3, detect_format(azw3))
    assert "正文段落甲乙丙" in text


def test_load_azw3_drm_rejected(tmp_path, monkeypatch):
    mobi = pytest.importorskip("mobi")
    azw3 = tmp_path / "locked.azw3"
    azw3.write_bytes(b"encrypted")

    def _boom(_path):
        raise RuntimeError("DRM encrypted book")

    monkeypatch.setattr(mobi, "extract", _boom)
    with pytest.raises(ValueError, match="DRM-protected Kindle/MOBI"):
        load_document(azw3, detect_format(azw3))
