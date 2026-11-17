"""Leximi i dokumenteve dhe ndarja e tekstit në pjesë (chunks)."""

import re
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


# Nëse një faqe PDF ka mesatarisht më pak karaktere se kjo, PDF-ja trajtohet si e skanuar.
MIN_CHARS_PER_PAGE = 80


def needs_ocr(text: str, pages: int) -> bool:
    return pages > 0 and len(text.strip()) / pages < MIN_CHARS_PER_PAGE


def _ocr_pdf(path: Path, max_pages: int | None = None) -> str:
    """Lexon PDF të skanuar me Tesseract (gjuha shqipe + anglisht)."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as exc:
        raise ValueError(
            "PDF-ja është e skanuar dhe duhet OCR. Instaloni pytesseract, pdf2image, "
            "Tesseract me gjuhën shqipe (sqi) dhe Poppler, ose përdorni Docker."
        ) from exc
    try:
        from pypdf import PdfReader

        page_count = len(PdfReader(str(path)).pages)
        if max_pages is not None and page_count > max_pages:
            raise ValueError(
                f"PDF-ja ka {page_count} faqe dhe tejkalon kufirin OCR prej {max_pages} faqesh."
            )
        images = convert_from_path(str(path), dpi=220)
        return "\n\n".join(pytesseract.image_to_string(img, lang="sqi+eng") for img in images)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"OCR dështoi për këtë PDF: {exc}") from exc


def extract_text(path: Path, max_ocr_pages: int | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        if needs_ocr(text, len(reader.pages)):
            if max_ocr_pages is None:
                return _ocr_pdf(path)
            return _ocr_pdf(path, max_pages=max_ocr_pages)
        return text
    if suffix == ".docx":
        import docx

        document = docx.Document(str(path))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n\n".join(parts)
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Formati {suffix} nuk mbështetet. Përdorni PDF, DOCX, TXT ose MD.")


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_long(paragraph: str, size: int) -> list[str]:
    """Ndan një paragraf shumë të gjatë sipas fjalive, e në rast nevoje me prerje të fortë."""
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > size:
            if current:
                parts.append(current)
                current = ""
            cut = sentence.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            parts.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > size:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return [p for p in parts if p]


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Bashkon paragrafët në pjesë rreth `size` karaktere, me mbivendosje `overlap`."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        pieces.extend(_split_long(paragraph, size) if len(paragraph) > size else [paragraph])

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 2 + len(piece) > size:
            chunks.append(current)
            tail = current[-overlap:] if overlap > 0 else ""
            if " " in tail:
                tail = tail[tail.find(" ") + 1 :]
            current = f"{tail}\n\n{piece}" if tail else piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks
