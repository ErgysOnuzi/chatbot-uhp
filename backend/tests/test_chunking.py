from pathlib import Path

import pytest

from app.chunking import chunk_text, clean_text, extract_text, needs_ocr


def test_needs_ocr_detects_scanned_pdf():
    assert needs_ocr("", 5)
    assert needs_ocr("  \n\n  12  ", 3)
    assert not needs_ocr("Neni 1. " + "tekst i rregullores " * 20, 1)
    assert not needs_ocr("", 0)


def test_scanned_pdf_goes_to_ocr(tmp_path: Path, monkeypatch):
    from pypdf import PdfWriter

    import app.chunking as chunking

    # PDF me një faqe pa tekst (si PDF e skanuar) duhet të kalojë te OCR
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    f = tmp_path / "skanuar.pdf"
    with f.open("wb") as out:
        writer.write(out)
    monkeypatch.setattr(chunking, "_ocr_pdf", lambda path: "Neni 1 nga OCR")
    assert extract_text(f) == "Neni 1 nga OCR"


def test_large_scanned_pdf_respects_ocr_page_limit(tmp_path: Path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    f = tmp_path / "madh.pdf"
    with f.open("wb") as out:
        writer.write(out)
    with pytest.raises(ValueError, match="kufirin OCR"):
        extract_text(f, max_ocr_pages=1)


def test_clean_text_collapses_whitespace():
    raw = "Afati   i provimit\r\n\r\n\r\n\r\nështë  janari   2027"
    assert clean_text(raw) == "Afati i provimit\n\nështë janari 2027"


def test_short_text_is_one_chunk():
    assert chunk_text("Një paragraf i shkurtër.") == ["Një paragraf i shkurtër."]


def test_chunks_respect_size_with_small_tolerance():
    paragraphs = [f"Paragrafi {i}. " + "fjalë " * 40 for i in range(30)]
    chunks = chunk_text("\n\n".join(paragraphs), size=500, overlap=80)
    assert len(chunks) > 1
    # mbivendosja mund ta tejkalojë pak madhësinë, por jo shumë
    assert all(len(c) <= 500 + 80 + 2 for c in chunks)


def test_overlap_repeats_end_of_previous_chunk():
    paragraphs = [f"Hapi {i}: " + "detaj " * 30 for i in range(10)]
    chunks = chunk_text("\n\n".join(paragraphs), size=400, overlap=60)
    for previous, current in zip(chunks, chunks[1:]):
        start = current.split("\n\n")[0]
        assert start in previous


def test_very_long_paragraph_is_split():
    text = "Kjo është një fjali e gjatë pa ndërprerje. " * 100
    chunks = chunk_text(text, size=300, overlap=0)
    assert len(chunks) > 5
    assert all(len(c) <= 300 for c in chunks)


def test_no_content_is_lost():
    paragraphs = [f"Rregulli numër {i} duhet të ruhet." for i in range(50)]
    joined = "\n\n".join(chunk_text("\n\n".join(paragraphs), size=200, overlap=40))
    for p in paragraphs:
        assert p in joined


def test_extract_text_txt(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("Përshëndetje studentë", encoding="utf-8")
    assert extract_text(f) == "Përshëndetje studentë"


def test_extract_text_docx(tmp_path: Path):
    import docx

    d = docx.Document()
    d.add_paragraph("Afati për fletëparaqitje")
    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Provimi"
    table.cell(0, 1).text = "15 janar"
    f = tmp_path / "a.docx"
    d.save(str(f))
    text = extract_text(f)
    assert "Afati për fletëparaqitje" in text
    assert "Provimi | 15 janar" in text


def test_unsupported_format(tmp_path: Path):
    f = tmp_path / "a.xlsx"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        extract_text(f)
