from types import SimpleNamespace

from app.search import fold, query_terms


def _row(doc_id, text, rank):
    chunk = SimpleNamespace(document_id=doc_id, search_text=fold(text), content=text)
    return (chunk, 0.7, rank)


def test_coverage_beats_repetition_and_documents_are_capped():
    from app.search import rank_keyword_rows

    terms = query_terms("Cilat lëndë ka provimi pranues në Shkenca Kompjuterike?")
    archive = [_row(1, "Orari i provimeve, orari i provimeve, provimi, provimi", 1.6) for _ in range(5)]
    answer = _row(2, "Provimi pranues për Shkenca Kompjuterike: lëndët Matematikë dhe Informatikë", 0.4)
    ranked = rank_keyword_rows([*archive, answer], terms, limit=10)
    assert ranked[0] is answer
    assert sum(1 for r in ranked if r[0].document_id == 1) == 2
