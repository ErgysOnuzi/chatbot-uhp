"""Rregullat në docs/universiteti/crawl.json: dokumentet e shfuqizuara dhe të brendshme përjashtohen."""

from pathlib import Path

from app.crawler import CrawlConfig, URLFilter

CONFIG = Path(__file__).resolve().parents[2] / "docs" / "universiteti" / "crawl.json"
BASE = "https://uni-prizren.com/wp-content/uploads/"


def kind(url: str) -> str:
    return URLFilter(CrawlConfig.from_file(CONFIG)).classify(url).kind


def test_archived_documents_are_excluded():
    assert kind(BASE + "2023/01/Doracaku-final-2.pdf") == "skip"  # doracaku 2020, i shfuqizuar
    assert kind(BASE + "2025/06/Rregullore_per_mobilitet_te_studenteve_950101.pdf") == "skip"


def test_current_student_documents_are_kept():
    assert kind(BASE + "2023/01/Doracaku-per-student.pdf") == "document"
    assert kind(BASE + "2022/10/01-447A.pdf") == "document"  # punimi i diplomës
    assert kind(BASE + "2025/02/Rregullore-per-ndarjen-e-bursave.pdf") == "document"


def test_internal_staff_documents_are_excluded():
    assert kind(BASE + "2026/04/Rregullore-per-Menaxhimin-e-Telefonise-Fixe.pdf") == "skip"
