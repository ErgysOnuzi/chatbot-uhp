from app.sources import select_sources


def test_only_close_documents_are_shown():
    hits = [(1, "Taksat administrative", 0.21), (1, "Taksat administrative", 0.24),
            (2, "Tarifat", 0.27), (3, "Rregullore për pagat e stafit", 0.45)]
    assert [s["title"] for s in select_sources(hits)] == ["Taksat administrative", "Tarifat"]


def test_limit_and_order():
    hits = [(i, f"D{i}", 0.30 + i / 100) for i in range(6)]
    assert [s["id"] for s in select_sources(hits, margin=1, limit=3)] == [0, 1, 2]


def test_empty():
    assert select_sources([]) == []
