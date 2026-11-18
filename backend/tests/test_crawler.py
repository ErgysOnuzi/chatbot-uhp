from pathlib import Path
from datetime import date

from app.crawler import (
    CrawlConfig,
    CrawlManifest,
    RobotsGate,
    URLFilter,
    category_for,
    extract_page,
    is_generic_title,
    is_internal_document,
    is_news_post,
    needs_refresh,
    publication_date_from_url,
    regulation_version_key,
    twelve_months_ago,
)


def config(tmp_path: Path) -> CrawlConfig:
    return CrawlConfig(
        seeds=["https://fshk.uni-prizren.com/"],
        allowed_domains=["uni-prizren.com", "fshk.uni-prizren.com"],
        include_patterns=[
            r"^https://fshk\.uni-prizren\.com/",
            r"^https://uni-prizren\.com/studentet/",
        ],
        exclude_patterns=[],
        max_depth=3,
        delay=0,
    )


def test_html_extraction_keeps_main_content_tables_and_albanian_letters():
    html = (Path(__file__).parent / "fixtures" / "sample_page.html").read_text(encoding="utf-8")
    page = extract_page(html, "https://fshk.uni-prizren.com/orari/")

    assert page.title == "Orari i provimeve – FSHK"
    assert "Provimet e afatit dimëror" in page.text
    assert "Data | Lënda | Salla" in page.text
    assert "15 janar | Programimi | A-201" in page.text
    assert "MENU KRYESOR" not in page.text
    assert "SIDEBAR" not in page.text
    assert "Përdorimi i cookies" not in page.text
    assert "FOOTER" not in page.text
    assert "ë" in page.text and "ç" in page.text


def test_url_filter_allows_only_public_student_pages_and_documents(tmp_path: Path):
    policy = URLFilter(config(tmp_path))

    assert policy.classify("https://fshk.uni-prizren.com/rregulloret/").kind == "page"
    assert policy.classify("https://uni-prizren.com/studentet/smu/").kind == "page"
    assert policy.classify("https://uni-prizren.com/wp-content/uploads/rregullore.pdf").kind == "document"
    assert policy.classify("https://drive.google.com/drive/folders/abc").kind == "drive"
    assert policy.classify("https://example.com/studentet/").kind == "skip"
    assert policy.classify("https://fshk.uni-prizren.com/wp-admin/").kind == "skip"
    assert policy.classify("https://uni-prizren.com/wp-login.php").kind == "skip"
    assert policy.classify("https://fshk.uni-prizren.com/tag/studentet/").kind == "skip"
    assert policy.classify("https://fshk.uni-prizren.com/search/?q=provimi").kind == "skip"
    assert policy.classify("https://fshk.uni-prizren.com/rezultatet-provimeve/").kind == "skip"
    assert policy.classify("https://fshk.uni-prizren.com/lista-e-kandidateve/").kind == "skip"
    assert policy.classify("https://fshk.uni-prizren.com/logo.png").kind == "skip"
    assert policy.classify("https://uni-prizren.com/lajme/").kind == "skip"


def test_manifest_skips_unchanged_and_refreshes_changed_or_missing(tmp_path: Path):
    path = tmp_path / "crawl_manifest.json"
    manifest = CrawlManifest(path)
    url = "https://fshk.uni-prizren.com/orari/"
    digest = "a" * 64
    manifest.record(url, digest, 42, "Orari", "page", "ingested")
    manifest.save()

    loaded = CrawlManifest(path)
    entry = loaded.get(url)
    assert entry is not None
    assert entry.document_id == 42
    assert not needs_refresh(entry, digest, lambda document_id: document_id == 42)
    assert needs_refresh(entry, "b" * 64, lambda document_id: document_id == 42)
    assert needs_refresh(entry, digest, lambda document_id: False)


def test_robots_gate_obeys_fake_robots_parser():
    robots = "User-agent: *\nDisallow: /private/\nAllow: /\n"

    def loader(_: str) -> tuple[int, str]:
        return 200, robots

    gate = RobotsGate(loader)
    assert gate.can_fetch("https://fshk.uni-prizren.com/studentet/")
    assert not gate.can_fetch("https://fshk.uni-prizren.com/private/listat/")


def test_category_is_derived_from_faculty_url_section():
    assert category_for("https://fshk.uni-prizren.com/bachelor/teknologji-e-informimit-dhe-telekomunikimit/") == "FSHK – TIT"
    assert category_for("https://uni-prizren.com/upz/rregulloret-dhe-dokumentet/") == "Rregullore"
    assert category_for("https://uni-prizren.com/studentet/smu/") == "Studentët"


def test_title_uses_main_heading_and_rejects_generic_site_title():
    page = extract_page(
        """
        <html><head><title>Universiteti "Ukshin Hoti" Prizren</title></head>
        <body><header><h1>Universiteti "Ukshin Hoti" Prizren</h1></header>
        <main><h2>Orari i provimeve</h2><p>Përmbajtja kryesore.</p></main></body></html>
        """,
        "https://fshk.uni-prizren.com/orari/",
    )
    assert page.title == "Orari i provimeve"
    assert not is_generic_title(page.title)
    assert is_generic_title('Universiteti "Ukshin Hoti" Prizren')
    assert is_generic_title("Dokumente")
    assert is_generic_title("Video")


def test_publication_date_and_news_cutoff():
    html = """
    <html><head><meta property="article:published_time" content="2026-02-03T08:00:00Z"></head>
    <body class="single-post category-lajme"><main><h1>Njoftim i ri</h1><p>Tekst.</p></main></body></html>
    """
    page = extract_page(html, "https://fshk.uni-prizren.com/njoftim/")
    assert page.published_at == date(2026, 2, 3)
    assert is_news_post("https://fshk.uni-prizren.com/2025/04/12/njoftim/", page.categories)
    assert publication_date_from_url("https://fshk.uni-prizren.com/2025/04/12/njoftim/") == date(2025, 4, 12)
    assert twelve_months_ago(date(2026, 11, 17)) == date(2025, 11, 17)


def test_old_post_date_is_read_from_main_article_not_sidebar():
    html = """
    <html><body class="single-post">
      <aside><article><time datetime="2026-06-04T07:18:42Z">2026</time></article></aside>
      <article class="type-post category-lajme">
        <h1>Njoftim i vjetër</h1>
        <div class="entry-meta"><time datetime="2021-09-12T20:27:53Z">2021</time></div>
        <p>Përmbajtja e njoftimit.</p>
      </article>
    </body></html>
    """
    page = extract_page(html, "https://fshk.uni-prizren.com/njoftim-i-vjeter/")
    assert page.published_at == date(2021, 9, 12)
    assert "lajme" in page.categories


def test_internal_salary_minutes_and_project_meetings_are_excluded():
    assert is_internal_document(
        "https://uni-prizren.com/wp-content/uploads/rregullorja-per-te-ardhurat-personale.pdf",
        "Rregullorja",
    )
    assert is_internal_document(
        "https://uni-prizren.com/wp-content/uploads/rregullorja-per-te-ardhura-personale.pdf",
        "Rregullorja",
    )
    assert is_internal_document("https://fshk.uni-prizren.com/procesverbal-2026/", "Procesverbal")
    assert is_internal_document(
        "https://fshk.uni-prizren.com/takim-projektit/",
        "Takim i projektit LAIA",
    )
    assert is_internal_document(
        "https://uni-prizren.com/wp-content/uploads/rregullorja-komisionit-statutar.pdf",
        "Rregullorja",
    )
    assert not is_internal_document(
        "https://uni-prizren.com/studentet/tarifat-per-studente/",
        "Taksat administrative për studentë",
    )


def test_regulation_versions_have_same_normalized_key():
    old = regulation_version_key("Rregullorja për studimet Bachelor 25.11.2022")
    new = regulation_version_key("Rregullorja per studimet Bachelor - e korrigjuar 2024")
    assert old == new
    assert old == "rregullorja per studimet bachelor"
    assert regulation_version_key("Njoftim për provime") is None
