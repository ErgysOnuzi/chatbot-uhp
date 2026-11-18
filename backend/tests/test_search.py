from datetime import date

from app.search import (
    fold, is_stale, matched_terms, news_date_from_text, query_terms, rrf, stem, to_tsquery, upload_date,
)


def test_fold_removes_diacritics_and_punctuation():
    assert fold("Semestri i gjashtë, çfarë?") == "semestri i gjashte cfare"


def test_query_terms_drop_stopwords_and_handle_no_diacritics():
    # Pyetja e shkruar pa ë dhe ç jep të njëjtat terma si ajo me shkronja të sakta.
    expected = ["lende", "semestrin", "gjashte", "6", "tit"]
    assert query_terms("Cilat lëndë janë në semestrin e gjashtë të TIT?") == expected
    assert query_terms("cilat lende jane ne semestrin e gjashte te TIT") == expected


def test_stem_matches_inflected_forms():
    text = fold("Lëndët e semestrit të gjashtë: Kompjutimi Cloud")
    terms = query_terms("lëndë semestrin gjashtë")
    assert stem("semestrin") == "semestr"
    assert matched_terms(terms, text) == 3


def test_tsquery_uses_prefixes_and_or():
    assert to_tsquery(["semestrin", "gjashte", "tit"]) == "semestr:* | gjash:* | tit:*"
    assert to_tsquery([]) is None


def test_numbers_and_codes_are_kept():
    assert "2022" in query_terms("Rregullorja e vitit 2022, neni 15")
    assert "15" in query_terms("neni 15")


def test_rrf_rewards_items_found_by_both_methods():
    vector = [10, 11, 12, 13]
    keyword = [13, 20, 10]
    fused = rrf([vector, keyword])
    assert fused[0] == 10  # i dyti te vektorët, i treti te fjalët kyçe
    assert fused[1] == 13  # i fundit te vektorët, por i pari te fjalët kyçe
    assert set(fused) == {10, 11, 12, 13, 20}


def test_old_news_is_stale_but_regulations_are_not():
    today = date(2026, 11, 18)
    assert is_stale(True, date(2022, 5, 1), today)
    assert is_stale(True, None, today)
    assert not is_stale(True, date(2026, 6, 1), today)
    assert not is_stale(False, date(2019, 12, 30), today)  # rregulloret nuk vjetrohen sipas datës


def test_dates_from_url_and_text():
    assert upload_date("https://uni-prizren.com/wp-content/uploads/2024/11/x.pdf") == date(2024, 11, 1)
    assert upload_date("https://fshk.uni-prizren.com/bachelor/") is None
    assert news_date_from_text("Data e publikimit: 2026-06-04\n\nStudentët...") == date(2026, 6, 4)
    assert news_date_from_text("Teksti pa datë") is None


def test_ordinal_words_match_numbers_in_documents():
    document = fold("Semestri 6: Përmbajtja dinamike e inxhinierisë së web-it, Kompjutimi Cloud")
    assert matched_terms(query_terms("semestri i gjashtë"), document) >= 2
    assert "gjashte" in query_terms("semestri 6")
