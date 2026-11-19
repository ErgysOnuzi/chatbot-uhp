"""Crawler i kufizuar për faqet publike të Universitetit "Ukshin Hoti" Prizren."""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from .chunking import clean_text, needs_ocr
from .config import settings
from .db import SessionLocal, init_db
from .models import Document
from .rag import ingest_file

USER_AGENT = "chatbot-uhp/0.1 (student diploma project)"
DOCUMENT_SUFFIXES = {".pdf", ".docx"}
SKIP_SUFFIXES = {
    ".7z",
    ".avi",
    ".bmp",
    ".css",
    ".csv",
    ".doc",
    ".eot",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".m4v",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".ogg",
    ".otf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".svg",
    ".tar",
    ".tif",
    ".tiff",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}

# Këto filtra zbatohen gjithnjë, edhe nëse mungojnë nga konfigurimi.
MANDATORY_EXCLUDES = (
    r"/wp-admin(?:/|$)",
    r"/wp-login\.php",
    r"/wp-json(?:/|$)",
    r"/xmlrpc\.php(?:$|\?)",
    r"/feed(?:/|$)",
    r"/comments(?:/|$)",
    r"[?&]replytocom=",
    r"(?:[?&](?:s|search|query)=|/search(?:/|$)|/kerko(?:/|$))",
    r"/(?:tag|author)(?:/|$)",
    r"(?:rezultatet|rezultati|listat|lista|liste)(?:/|$|[-_.?])",
)

SENSITIVE_TITLE_RE = re.compile(
    r"\b(?:rezultatet|rezultati|lista|listat|listë|listës|liste)\b",
    re.IGNORECASE,
)

GENERIC_TITLE_RE = re.compile(
    r"^(?:"
    r"dokumente|dokumentet|video|videos|foto|fotografi|fotografitë|ballina|home|"
    r"lajme|lajmet|ngjarje|evente|events|agjenda|"
    r"universiteti(?:\s+i\s+prizrenit)?(?:\s+[\"“”']?ukshin hoti[\"“”']?)?(?:\s+prizren)?|"
    r"university of prizren|upz"
    r")$",
    re.IGNORECASE,
)

INTERNAL_DOCUMENT_RE = re.compile(
    r"\b(?:"
    r"te ardhura(?:t)? personale|paga|pagat|pagar|kompensime.*personel|shtesat.*paga|"
    r"procesverbal|sistematizim\w*.*vende\w*.*pun\w*|rregullore.*personel\w*|"
    r"rregullore.*administrat.*intern|udhezues.*administrat.*intern|"
    r"komision.*statutar|rregullore.*botim|rregullore.*kerkime shkencore|"
    r"rregullore.*organizim.*pune|prokurim|rregullore.*(?:financ|buxhet)|arkiva|"
    r"kodi i etikes.*personel\w*|angazhim.*bashkepunetore.*jashtem|organizim\w*.*brendshem"
    r")\b",
    re.IGNORECASE,
)

PROJECT_MEETING_RE = re.compile(
    r"(?:"
    r"\b(?:takim|takimi|takimin|mbledhje|mbledhja|mbledhjen)\b.*"
    r"\b(?:projekt|projekti|projektit|bord|bordi|bki|laia|erasmus)\b|"
    r"\b(?:projekt|projekti|projektit|bord|bordi|bki|laia|erasmus)\b.*"
    r"\b(?:takim|takimi|takimin|mbledhje|mbledhja|mbledhjen)\b"
    r")",
    re.IGNORECASE,
)

DATE_URL_RE = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})(?:/|$)")
DATE_TEXT_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b")
YEAR_RE = re.compile(r"\b20\d{2}\b")

MAIN_SELECTORS = (
    "main article",
    "main",
    "article",
    ".entry-content",
    ".elementor-widget-theme-post-content",
    ".post-content",
    ".page-content",
    "#content",
    "body",
)

NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "form",
    "nav",
    "header",
    "footer",
    "aside",
    "#primary-menu",
    "#mobile-menu",
    ".main-nav",
    ".mobile-main-nav",
    ".mega-menu",
    ".sidebar-content",
    ".wpb_widgetised_column",
    ".widget",
    ".breadcrumbs",
    ".dt-breadcrumbs-shortcode",
    ".assistive-text",
    ".post-entry-meta",
    ".social-share",
    ".share-buttons",
    ".related-posts",
    ".cmplz-cookiebanner",
    ".cmplz-manage-consent",
    "[class*='cookie']",
    "[id*='cookie']",
)


class CrawlError(RuntimeError):
    """Gabim i konfigurimit ose i rrjedhës së crawl-it."""


class FetchError(CrawlError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RobotsDenied(FetchError):
    """robots.txt nuk lejon kërkesën."""


@dataclass(frozen=True)
class CrawlConfig:
    seeds: list[str]
    allowed_domains: list[str]
    include_patterns: list[str]
    exclude_patterns: list[str]
    max_depth: int = 3
    delay: float = 1.5
    max_pages: int = 400
    timeout: float = 30.0
    retries: int = 3
    max_runtime_seconds: int = 900
    max_ocr_pages: int = 40
    sitemaps: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> "CrawlConfig":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CrawlError(f"Konfigurimi i crawl-it nuk lexohet: {exc}") from exc

        if not raw.get("seeds"):
            raise CrawlError("crawl.json duhet të përmbajë të paktën një seed.")
        if not raw.get("allowed_domains"):
            raise CrawlError("crawl.json duhet të përmbajë allowed_domains.")

        config = cls(
            seeds=[str(url).strip() for url in raw["seeds"] if str(url).strip()],
            allowed_domains=[
                str(domain).strip().lower().removeprefix("www.").rstrip(".")
                for domain in raw["allowed_domains"]
                if str(domain).strip()
            ],
            include_patterns=[str(pattern) for pattern in raw.get("include_patterns", [])],
            exclude_patterns=[str(pattern) for pattern in raw.get("exclude_patterns", [])],
            max_depth=int(raw.get("max_depth", 3)),
            delay=float(raw.get("delay", 1.5)),
            max_pages=int(raw.get("max_pages", 400)),
            timeout=float(raw.get("timeout", 30)),
            retries=int(raw.get("retries", 3)),
            max_runtime_seconds=int(raw.get("max_runtime_seconds", 900)),
            max_ocr_pages=int(raw.get("max_ocr_pages", 40)),
            sitemaps=[str(url).strip() for url in raw.get("sitemaps", []) if str(url).strip()],
        )
        if (
            config.max_depth < 0
            or config.delay < 0
            or config.max_pages < 1
            or config.max_runtime_seconds < 1
            or config.max_ocr_pages < 1
        ):
            raise CrawlError("max_depth, delay, max_pages, max_runtime_seconds ose max_ocr_pages ka vlerë të pavlefshme.")
        return config


@dataclass(frozen=True)
class Link:
    url: str
    text: str = ""


@dataclass(frozen=True)
class URLDecision:
    kind: str
    reason: str = ""


def canonical_url(url: str) -> str:
    """Normalizon URL-në për deduplikim dhe manifest."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if scheme not in {"http", "https"} or not host:
        return ""
    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", urlencode(sorted(query)), ""))


class URLFilter:
    def __init__(self, config: CrawlConfig):
        self.allowed_domains = tuple(config.allowed_domains)
        self.includes = tuple(re.compile(pattern, re.IGNORECASE) for pattern in config.include_patterns)
        try:
            self.excludes = tuple(
                re.compile(pattern, re.IGNORECASE)
                for pattern in (*MANDATORY_EXCLUDES, *config.exclude_patterns)
            )
        except re.error as exc:
            raise CrawlError(f"Pattern i pavlefshëm në crawl.json: {exc}") from exc

    def _domain_allowed(self, host: str) -> bool:
        return any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)

    def is_domain_allowed(self, url: str) -> bool:
        return self._domain_allowed((urlparse(url).hostname or "").lower())

    def is_drive(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in {"drive.google.com", "docs.google.com"}

    def classify(self, url: str) -> URLDecision:
        normalized = canonical_url(url)
        if not normalized:
            return URLDecision("skip", "URL relative ose jo HTTP")
        parsed = urlparse(normalized)
        if self.is_drive(normalized):
            return URLDecision("drive", "Google Drive nuk ndiqet")
        if not self._domain_allowed(parsed.hostname or ""):
            return URLDecision("skip", "domain i jashtëm")
        if any(pattern.search(normalized) for pattern in self.excludes):
            return URLDecision("skip", "URL i përjashtuar")

        suffix = Path(parsed.path).suffix.lower()
        if suffix in DOCUMENT_SUFFIXES:
            return URLDecision("document")
        if suffix in SKIP_SUFFIXES or parsed.path.startswith("/wp-content/"):
            return URLDecision("skip", "skedar jo-dokument")
        if self.includes and not any(pattern.search(normalized) for pattern in self.includes):
            return URLDecision("skip", "nuk përket seksioneve studentore")
        return URLDecision("page")


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    headers: dict[str, str]
    data: bytes

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    @property
    def charset(self) -> str:
        content_type = self.headers.get("content-type", "")
        match = re.search(r"charset=([^\s;]+)", content_type, re.IGNORECASE)
        return match.group(1) if match else "utf-8"


class RobotsGate:
    """Cache për robots.txt; loader-i injektohet që testet të mos përdorin rrjet."""

    def __init__(
        self,
        loader: Callable[[str], tuple[int, str]],
        user_agent: str = USER_AGENT,
    ):
        self._loader = loader
        self._user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin)
        parser = self._parsers[origin]
        if parser is None:
            return False
        return parser.can_fetch(self._user_agent, url)

    def _load(self, origin: str) -> urllib.robotparser.RobotFileParser | None:
        try:
            status, body = self._loader(f"{origin}/robots.txt")
        except FetchError:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        if status in {401, 403}:
            parser.disallow_all = True
        elif 400 <= status < 500:
            parser.allow_all = True
        elif 200 <= status < 300:
            parser.parse(body.splitlines())
        else:
            return None
        return parser


class PoliteFetcher:
    """Klient GET serial, me robots.txt, delay dhe retry me backoff."""

    def __init__(self, config: CrawlConfig, max_bytes: int = 30 * 1024 * 1024):
        self.config = config
        self.max_bytes = max_bytes
        self._last_request = 0.0
        self.robots = RobotsGate(self._load_robots)

    def _wait(self) -> None:
        if self._last_request:
            remaining = self.config.delay - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)

    def _load_robots(self, url: str) -> tuple[int, str]:
        response = self._request(url, obey_robots=False, allowed_statuses={401, 403, 404, 410})
        return response.status, response.data.decode("utf-8", errors="replace")

    def get(self, url: str, obey_robots: bool = True) -> FetchResponse:
        return self._request(url, obey_robots=obey_robots)

    def _request(
        self,
        url: str,
        obey_robots: bool,
        allowed_statuses: set[int] | None = None,
    ) -> FetchResponse:
        allowed_statuses = allowed_statuses or set()
        if obey_robots and not self.robots.can_fetch(url):
            raise RobotsDenied(f"robots.txt nuk lejon {url}")

        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            self._wait()
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*;q=0.8"},
                method="GET",
            )
            self._last_request = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                    data = response.read(self.max_bytes + 1)
                    if len(data) > self.max_bytes:
                        raise FetchError(f"përgjigjja tejkalon {self.max_bytes // (1024 * 1024)} MB")
                    headers = {key.lower(): value for key, value in response.headers.items()}
                    return FetchResponse(
                        url=response.geturl(),
                        status=response.status,
                        headers=headers,
                        data=data,
                    )
            except urllib.error.HTTPError as exc:
                if exc.code in allowed_statuses:
                    data = exc.read(self.max_bytes + 1)
                    headers = {key.lower(): value for key, value in exc.headers.items()}
                    return FetchResponse(url=url, status=exc.code, headers=headers, data=data)
                last_error = FetchError(f"HTTP {exc.code}", status=exc.code)
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = FetchError(f"lidhja dështoi: {exc}")

            if attempt < self.config.retries:
                time.sleep(2**attempt)

        raise last_error or FetchError(f"Fetch dështoi: {url}")


@dataclass
class ExtractedPage:
    title: str
    text: str
    links: list[Link]
    published_at: date | None = None
    categories: tuple[str, ...] = ()


def _inline_text(node: Tag) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _readable_tables(root: Tag) -> None:
    for table in reversed(root.find_all("table")):
        rows: list[str] = []
        for row in table.find_all("tr"):
            cells = [_inline_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with(NavigableString("\n" + "\n".join(rows) + "\n"))


def _mark_headings_and_lists(root: Tag) -> None:
    for heading in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        level = int(heading.name[1])
        heading.insert_before(NavigableString(f"\n{'#' * level} "))
        heading.insert_after(NavigableString("\n"))
    for item in root.find_all("li"):
        item.insert(0, NavigableString("- "))
    for br in root.find_all("br"):
        br.replace_with(NavigableString("\n"))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return datetime.fromisoformat(stripped.replace("Z", "+00:00")).date()
    except ValueError:
        match = DATE_TEXT_RE.search(stripped)
        if not match:
            return None
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None


def publication_date_from_url(url: str) -> date | None:
    match = DATE_URL_RE.search(urlparse(url).path)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _published_at(soup: BeautifulSoup, base_url: str) -> date | None:
    selectors = (
        "meta[property='article:published_time']",
        "meta[name='article:published_time']",
        "meta[name='date']",
        "meta[itemprop='datePublished']",
    )
    for selector in selectors:
        element = soup.select_one(selector)
        if element and element.get("content"):
            parsed = _parse_date(str(element["content"]))
            if parsed:
                return parsed
    for selector in (
        "article.type-post .entry-meta time[datetime]",
        "article.type-post .post-meta time[datetime]",
        "main article time[datetime]",
    ):
        element = soup.select_one(selector)
        if element:
            parsed = _parse_date(str(element.get("datetime", "")))
            if parsed:
                return parsed
    for element in soup.select("time[datetime]"):
        parsed = _parse_date(str(element.get("datetime", "")))
        if parsed:
            return parsed
    for script in soup.find_all("script", type="application/ld+json"):
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', script.get_text())
        if match:
            parsed = _parse_date(match.group(1))
            if parsed:
                return parsed
    return publication_date_from_url(base_url)


def _categories(soup: BeautifulSoup) -> tuple[str, ...]:
    categories: set[str] = set()
    main_article = soup.select_one("article.type-post") or soup.find("article")
    for container in [soup.find("body"), main_article]:
        if isinstance(container, Tag):
            for class_name in container.get("class", []):
                if class_name.startswith("category-"):
                    categories.add(class_name.removeprefix("category-").lower())
    section = soup.select_one("meta[property='article:section']")
    if section and section.get("content"):
        categories.add(str(section["content"]).strip().lower())
    return tuple(sorted(categories))


def is_generic_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title).strip()
    return not normalized or bool(GENERIC_TITLE_RE.fullmatch(normalized))


def extract_page(html: bytes | str, base_url: str) -> ExtractedPage:
    """Kthen titullin, tekstin kryesor dhe lidhjet e një faqe HTML."""
    soup = BeautifulSoup(html, "lxml")
    published_at = _published_at(soup, base_url)
    categories = _categories(soup)
    links: list[Link] = []
    seen_links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if absolute not in seen_links:
            seen_links.add(absolute)
            links.append(Link(absolute, _inline_text(anchor)))

    for element in soup.select(", ".join(NOISE_SELECTORS)):
        element.decompose()

    root: Tag | None = None
    for selector in MAIN_SELECTORS:
        candidate = soup.select_one(selector)
        if candidate is not None:
            root = candidate
            break
    root = root or soup.body or soup

    for element in root.select(", ".join(NOISE_SELECTORS)):
        element.decompose()

    heading = root.select_one(".entry-title, h1")
    if heading is None:
        heading = root.find(["h2", "h3"])
    title = _inline_text(heading) if heading else ""
    title = re.sub(r"\s*[|–-]\s*UPZ.*$", "", title, flags=re.IGNORECASE).strip()

    _readable_tables(root)
    _mark_headings_and_lists(root)
    text = clean_text(root.get_text("\n"))
    return ExtractedPage(
        title=title[:255],
        text=text,
        links=links,
        published_at=published_at,
        categories=categories,
    )


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def is_internal_document(url: str, title: str) -> bool:
    subject = f"{_fold(unquote(url))} {_fold(title)}"
    return bool(INTERNAL_DOCUMENT_RE.search(subject) or PROJECT_MEETING_RE.search(subject))


def is_news_post(url: str, categories: tuple[str, ...] = ()) -> bool:
    path = urlparse(url).path.lower()
    if DATE_URL_RE.search(path):
        return True
    normalized_categories = {_fold(category) for category in categories}
    if normalized_categories & {"lajme", "ngjarje", "njoftime"}:
        return True
    return bool(re.search(r"/(?:category/)?(?:lajme|ngjarje|njoftime)(?:/|$)", path))


def twelve_months_ago(today: date) -> date:
    month_index = today.year * 12 + today.month - 1 - 12
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(today.day, monthrange(year, month)[1])
    return date(year, month, day)


def regulation_version_key(title: str) -> str | None:
    folded = _fold(title)
    if not re.search(r"\b(?:rregullore|rregullorja|statut|kodi i etikes|doracak|udhezues)\b", folded):
        return None
    folded = DATE_TEXT_RE.sub(" ", folded)
    folded = YEAR_RE.sub(" ", folded)
    folded = re.sub(r"\b\d+\b", " ", folded)
    folded = re.sub(
        r"\b(?:e|i)?\s*korrigjuar\b|\breviduar\b|\bversioni?\b|\bfinal(?:e)?\b|"
        r"\bne fuqi\b|\bshqip\b|\balb\b|\bpdf\b|\btekst\b",
        " ",
        folded,
    )
    return re.sub(r"\s+", " ", folded).strip()


def category_for(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.lower()
    if host.startswith("fshk."):
        if "teknologji-e-informimit" in path or "/tit-" in path:
            return "FSHK – TIT"
        if "dizajn-softueri" in path or "dizajnimi-i-softuereve" in path:
            return "FSHK – Dizajn Softueri"
        if "/master" in path:
            return "FSHK – Master"
        if "rregullore" in path or "vendimet-e-akreditimit" in path:
            return "Rregullore"
        if "taksa" in path or "tarifa" in path:
            return "Tarifa"
        return "FSHK"
    if "rregullore" in path or "statut" in path or "kodi-i-etikes" in path or "doracak" in path:
        return "Rregullore"
    if "kalendar" in path:
        return "Kalendari akademik"
    if "tarifa" in path:
        return "Tarifa"
    if "burs" in path:
        return "Bursat"
    if "bibliotek" in path:
        return "Biblioteka"
    if "erasmus" in path or "/zmj/" in path:
        return "Mobiliteti"
    if "karriera" in path:
        return "Karriera"
    if "studentet" in path or "regjistrim" in path or "smu" in path:
        return "Studentët"
    return "Universiteti"


@dataclass
class ManifestEntry:
    url: str
    content_sha256: str
    fetched_at: str
    document_id: int | None
    title: str = ""
    kind: str = ""
    status: str = "ingested"


class CrawlManifest:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, ManifestEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            entries = raw.get("entries", raw)
            for url, item in entries.items():
                self.entries[url] = ManifestEntry(**item)
        except (OSError, ValueError, TypeError):
            self.entries = {}

    def get(self, url: str) -> ManifestEntry | None:
        return self.entries.get(canonical_url(url))

    def record(
        self,
        url: str,
        content_sha256: str,
        document_id: int | None,
        title: str,
        kind: str,
        status: str,
    ) -> None:
        normalized = canonical_url(url)
        self.entries[normalized] = ManifestEntry(
            url=normalized,
            content_sha256=content_sha256,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            document_id=document_id,
            title=title,
            kind=kind,
            status=status,
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": {key: asdict(value) for key, value in self.entries.items()}}
        _atomic_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def needs_refresh(
    entry: ManifestEntry | None,
    content_sha256: str,
    document_exists: Callable[[int | None], bool],
) -> bool:
    if entry is None or entry.content_sha256 != content_sha256:
        return True
    if entry.status in {"empty", "duplicate", "privacy", "excluded", "superseded"}:
        return False
    return not document_exists(entry.document_id)


@dataclass
class CrawlStats:
    pages_crawled: int = 0
    ingested: int = 0
    updated: int = 0
    skipped: int = 0
    empty: int = 0
    documents: int = 0
    ocr_pdfs: list[str] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    drive_links: list[str] = field(default_factory=list)
    duplicates: list[tuple[str, str]] = field(default_factory=list)
    privacy_skipped: list[str] = field(default_factory=list)
    generic_skipped: list[str] = field(default_factory=list)
    old_news_skipped: list[str] = field(default_factory=list)
    internal_skipped: list[str] = field(default_factory=list)
    versions_removed: list[tuple[str, str]] = field(default_factory=list)
    disappeared: list[str] = field(default_factory=list)
    limit_reached: bool = False
    deadline_reached: bool = False


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _title_from_url(url: str) -> str:
    stem = unquote(Path(urlparse(url).path).stem)
    return re.sub(r"[_-]+", " ", stem).strip().capitalize() or "Dokument"


def _pdf_uses_ocr(data: bytes) -> bool:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return needs_ocr(text, len(reader.pages))
    except Exception:
        return False


class Crawler:
    def __init__(
        self,
        config: CrawlConfig,
        *,
        manifest_path: Path,
        report_path: Path,
        upload_dir: Path,
        dry_run: bool = False,
        max_pages: int | None = None,
    ):
        self.config = config
        self.url_filter = URLFilter(config)
        self.fetcher = PoliteFetcher(config)
        self.manifest = CrawlManifest(manifest_path)
        self.report_path = report_path
        self.upload_dir = upload_dir
        self.dry_run = dry_run
        self.max_pages = max_pages or config.max_pages
        self.stats = CrawlStats()
        self._visited: set[str] = set()
        self._queued: set[str] = set()
        self._document_dates: dict[str, date] = {}
        self._seen_digests: dict[str, tuple[str, int | None]] = {
            entry.content_sha256: (url, entry.document_id)
            for url, entry in self.manifest.entries.items()
            if entry.document_id is not None and entry.status == "ingested"
        }

    def run(self) -> CrawlStats:
        started = time.monotonic()
        queue: deque[tuple[str, int, str]] = deque()
        for seed in self.config.seeds:
            self._enqueue(queue, seed, 0, "")

        if not self.dry_run:
            init_db()
            self.upload_dir.mkdir(parents=True, exist_ok=True)

        with SessionLocal() as db:
            self._queue_sitemaps(queue)
            fetched = 0
            while queue:
                if time.monotonic() - started >= self.config.max_runtime_seconds:
                    self.stats.deadline_reached = True
                    break
                if fetched >= self.max_pages:
                    self.stats.limit_reached = True
                    break
                url, depth, title_hint = queue.popleft()
                decision = self.url_filter.classify(url)
                if decision.kind == "drive":
                    self._record_drive(url)
                    continue
                if decision.kind == "skip":
                    continue
                normalized = canonical_url(url)
                if normalized in self._visited:
                    continue
                self._visited.add(normalized)
                print(f"FETCH  {normalized}")
                fetched += 1
                try:
                    response = self.fetcher.get(normalized)
                    final_decision = self.url_filter.classify(response.url)
                    if final_decision.kind not in {"page", "document"}:
                        raise FetchError("ridrejtimi shkoi jashtë faqeve të lejuara")
                    if self._is_document(response, final_decision.kind):
                        self._process_document(db, normalized, response, title_hint)
                    else:
                        self._process_page(db, normalized, response, depth, queue)
                except RobotsDenied as exc:
                    self._failure(normalized, str(exc))
                except FetchError as exc:
                    self._failure(normalized, str(exc))
                except Exception as exc:  # një URL e dëmtuar nuk ndal crawl-in
                    self._failure(normalized, f"{type(exc).__name__}: {exc}")

        if not self.dry_run:
            self._dedupe_regulation_versions(db)

        if not (self.stats.limit_reached or self.stats.deadline_reached):
            self.stats.disappeared = sorted(set(self.manifest.entries) - self._visited)

        if not self.dry_run:
            self.manifest.save()
            _atomic_text(self.report_path, self._report())
        return self.stats

    def _enqueue(self, queue: deque[tuple[str, int, str]], url: str, depth: int, title: str) -> None:
        normalized = canonical_url(url)
        if not normalized:
            return
        decision = self.url_filter.classify(normalized)
        if decision.kind == "drive":
            self._record_drive(normalized)
            return
        if decision.kind == "skip":
            return
        if decision.kind == "page" and depth > self.config.max_depth:
            return
        if normalized not in self._queued and normalized not in self._visited:
            self._queued.add(normalized)
            queue.append((normalized, depth, title))

    def _queue_sitemaps(self, queue: deque[tuple[str, int, str]]) -> None:
        visited: set[str] = set()

        def read_sitemap(sitemap: str, depth: int = 0) -> None:
            normalized = canonical_url(sitemap)
            if (
                not normalized
                or normalized in visited
                or depth > 3
                or not self.url_filter.is_domain_allowed(normalized)
            ):
                return
            visited.add(normalized)
            try:
                response = self.fetcher.get(normalized)
                for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", response.data.decode("utf-8", "replace"), re.I):
                    target = canonical_url(loc.replace("&amp;", "&"))
                    if target.lower().endswith(".xml"):
                        read_sitemap(target, depth + 1)
                    else:
                        self._enqueue(queue, target, 1, "")
            except FetchError as exc:
                self._failure(normalized, f"sitemap: {exc}")

        for sitemap in self.config.sitemaps:
            read_sitemap(sitemap)

    def _is_document(self, response: FetchResponse, classified_kind: str) -> bool:
        return classified_kind == "document" or response.content_type in {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def _process_page(
        self,
        db: Session,
        url: str,
        response: FetchResponse,
        depth: int,
        queue: deque[tuple[str, int, str]],
    ) -> None:
        if "html" not in response.content_type and response.content_type:
            raise FetchError(f"përmbajtje e papritur: {response.content_type}")
        html = response.data.decode(response.charset, errors="replace")
        page = extract_page(html, response.url)
        for link in page.links:
            decision = self.url_filter.classify(link.url)
            if decision.kind == "drive":
                self._record_drive(link.url)
            elif decision.kind in {"page", "document"}:
                next_depth = depth + 1
                if decision.kind == "document" or next_depth <= self.config.max_depth:
                    self._enqueue(queue, link.url, next_depth, link.text)

        self.stats.pages_crawled += 1
        text = page.text.strip()
        if is_generic_title(page.title):
            self.stats.skipped += 1
            self.stats.generic_skipped.append(url)
            self._record_page_skip(url, text, page.title, "excluded")
            return
        if SENSITIVE_TITLE_RE.search(page.title):
            self.stats.skipped += 1
            self.stats.privacy_skipped.append(url)
            self._record_page_skip(url, text, page.title, "privacy")
            return
        if is_internal_document(url, page.title):
            self.stats.skipped += 1
            self.stats.internal_skipped.append(url)
            self._record_page_skip(url, text, page.title, "excluded")
            return

        published_at = page.published_at or _parse_date(page.title) or publication_date_from_url(url)
        if is_news_post(url, page.categories):
            if published_at is None or published_at < twelve_months_ago(date.today()):
                self.stats.skipped += 1
                self.stats.old_news_skipped.append(url)
                self._record_page_skip(url, text, page.title, "excluded")
                return
            text = f"Data e publikimit: {published_at.isoformat()}\n\n{text}"

        if published_at:
            self._document_dates[canonical_url(url)] = published_at
        if len(re.sub(r"\s+", "", text)) < 200:
            self.stats.empty += 1
            self._record_page_skip(url, text, page.title, "empty")
            return
        self._ingest_text(db, url, page.title, text, category_for(url))

    def _process_document(
        self,
        db: Session,
        url: str,
        response: FetchResponse,
        title_hint: str,
    ) -> None:
        suffix = Path(urlparse(response.url).path).suffix.lower()
        if suffix not in DOCUMENT_SUFFIXES:
            suffix = ".pdf" if response.content_type == "application/pdf" else ".docx"
        if suffix not in DOCUMENT_SUFFIXES:
            raise FetchError(f"formati {suffix or 'i panjohur'} nuk mbështetet")

        digest = hashlib.sha256(response.data).hexdigest()
        title = title_hint.strip()
        if len(title) < 3 or title.lower() in {"pdf", "shkarko", "lexo", "download"}:
            title = _title_from_url(response.url)
        if is_generic_title(title):
            self.stats.skipped += 1
            self.stats.generic_skipped.append(url)
            self._record_page_skip(url, title, title, "excluded")
            return
        if is_internal_document(url, title):
            self.stats.skipped += 1
            self.stats.internal_skipped.append(url)
            self._record_page_skip(url, title, title, "excluded")
            return
        published_at = publication_date_from_url(url)
        upload_date = re.search(r"/(20\d{2})/(\d{2})/", urlparse(url).path)
        if published_at is None and upload_date:
            try:
                published_at = date(int(upload_date.group(1)), int(upload_date.group(2)), 1)
            except ValueError:
                published_at = None
        if published_at:
            self._document_dates[canonical_url(url)] = published_at
        self.stats.documents += 1
        if suffix == ".pdf" and _pdf_uses_ocr(response.data):
            self.stats.ocr_pdfs.append(url)
        self._ingest_binary(db, url, title, response.data, suffix, digest)

    def _ingest_text(
        self,
        db: Session,
        url: str,
        title: str,
        text: str,
        category: str,
    ) -> None:
        digest = _sha(text)
        if self._skip_digest(db, url, digest):
            return
        if self.dry_run:
            return

        # Dokumenti i vjetër fshihet para se të shkruhet skedari i ri: kur përmbajtja është e njëjtë,
        # emri i skedarit (sipas hash-it) përputhet dhe fshirja e vjetrit do ta fshinte edhe të riun.
        self._replace_source(db, url)
        stored = self.upload_dir / f"crawl-{digest[:16]}.txt"
        stored.write_text(text + "\n", encoding="utf-8")
        document = ingest_file(db, stored, title, stored.name, category, source_url=url)
        self._record_ingested(url, digest, title, "page", document.id)

    def _ingest_binary(
        self,
        db: Session,
        url: str,
        title: str,
        data: bytes,
        suffix: str,
        digest: str,
    ) -> None:
        if self._skip_digest(db, url, digest):
            return
        if self.dry_run:
            return

        self._replace_source(db, url, fallback_title=title)
        stored = self.upload_dir / f"crawl-{digest[:16]}{suffix}"
        stored.write_bytes(data)
        document = ingest_file(
            db,
            stored,
            title,
            stored.name,
            category_for(url),
            source_url=url,
            max_ocr_pages=self.config.max_ocr_pages,
        )
        self._record_ingested(url, digest, title, "document", document.id)

    def _skip_digest(self, db: Session, url: str, digest: str) -> bool:
        normalized = canonical_url(url)
        entry = self.manifest.get(normalized)
        if not self.dry_run and not needs_refresh(
            entry,
            digest,
            lambda document_id: document_id is not None and db.get(Document, document_id) is not None,
        ):
            self.stats.skipped += 1
            if entry is not None:
                self.manifest.record(
                    normalized,
                    digest,
                    entry.document_id,
                    entry.title,
                    entry.kind,
                    entry.status,
                )
            return True

        duplicate = self._seen_digests.get(digest)
        if duplicate and duplicate[0] != normalized:
            self.stats.skipped += 1
            self.stats.duplicates.append((normalized, duplicate[0]))
            if not self.dry_run:
                self.manifest.record(normalized, digest, duplicate[1], "", "duplicate", "duplicate")
            return True
        return False

    def _replace_source(self, db: Session, source_url: str, fallback_title: str | None = None) -> None:
        query = select(Document).where(Document.source_url == source_url)
        documents = list(db.scalars(query).all())
        if fallback_title:
            legacy = db.scalars(
                select(Document).where(Document.title == fallback_title, Document.source_url.is_(None))
            ).all()
            documents.extend(legacy)
        seen: set[int] = set()
        for document in documents:
            if document.id in seen:
                continue
            seen.add(document.id)
            (self.upload_dir / document.filename).unlink(missing_ok=True)
            db.delete(document)
        if documents:
            db.commit()

    def _record_ingested(
        self,
        url: str,
        digest: str,
        title: str,
        kind: str,
        document_id: int,
    ) -> None:
        old = self.manifest.get(url)
        if old is not None and old.document_id is not None:
            self.stats.updated += 1
        else:
            self.stats.ingested += 1
        self._seen_digests[digest] = (canonical_url(url), document_id)
        self.manifest.record(url, digest, document_id, title, kind, "ingested")
        self.manifest.save()

    def _record_page_skip(self, url: str, text: str, title: str, status: str) -> None:
        if not self.dry_run:
            self.manifest.record(url, _sha(text), None, title, "page", status)
            self.manifest.save()

    def _dedupe_regulation_versions(self, db: Session) -> None:
        documents = list(
            db.scalars(select(Document).where(Document.source_url.is_not(None))).all()
        )
        groups: dict[str, list[Document]] = {}
        for document in documents:
            key = regulation_version_key(document.title)
            if key:
                groups.setdefault(key, []).append(document)

        for group in groups.values():
            if len(group) < 2:
                continue

            def version_date(document: Document) -> date:
                title_date = DATE_TEXT_RE.search(document.title)
                if title_date:
                    day, month, year = (int(part) for part in title_date.groups())
                    try:
                        return date(year, month, day)
                    except ValueError:
                        pass
                if document.source_url in self._document_dates:
                    return self._document_dates[document.source_url]
                if document.source_url:
                    parsed = publication_date_from_url(document.source_url)
                    if parsed:
                        return parsed
                return document.created_at.date()

            group.sort(key=lambda document: (version_date(document), document.id), reverse=True)
            newest = group[0]
            for old in group[1:]:
                if not old.source_url:
                    continue
                (self.upload_dir / old.filename).unlink(missing_ok=True)
                entry = self.manifest.get(old.source_url)
                if entry is not None:
                    self.manifest.record(
                        old.source_url,
                        entry.content_sha256,
                        newest.id,
                        entry.title,
                        entry.kind,
                        "superseded",
                    )
                self.stats.versions_removed.append(
                    (old.title, newest.title)
                )
                db.delete(old)
            db.commit()

    def _record_drive(self, url: str) -> None:
        if url not in self.stats.drive_links:
            self.stats.drive_links.append(url)

    def _failure(self, url: str, reason: str) -> None:
        self.stats.failures.append((url, reason))

    def _report(self) -> str:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "# Raporti i crawl-it",
            "",
            f"- Krijuar: {generated}",
            f"- Faqe HTML të lexuara: {self.stats.pages_crawled}",
            f"- Dokumente të reja: {self.stats.ingested}",
            f"- Dokumente të përditësuara: {self.stats.updated}",
            f"- URL të anashkaluara: {self.stats.skipped}",
            f"- Faqe të anashkaluara për privatësi: {len(self.stats.privacy_skipped)}",
            f"- Tituj gjenerikë të anashkaluar: {len(self.stats.generic_skipped)}",
            f"- Lajme më të vjetra se 12 muaj: {len(self.stats.old_news_skipped)}",
            f"- Dokumente të brendshme të anashkaluara: {len(self.stats.internal_skipped)}",
            f"- Versione të vjetra rregulloresh të hequra: {len(self.stats.versions_removed)}",
            f"- Faqe pothuajse bosh: {self.stats.empty}",
            f"- PDF të identifikuara për OCR: {len(self.stats.ocr_pdfs)}",
            f"- Dështime: {len(self.stats.failures)}",
            f"- Kufiri i faqeve u arrit: {'po' if self.stats.limit_reached else 'jo'}",
            f"- Afati kohor i run-it u arrit: {'po' if self.stats.deadline_reached else 'jo'}",
            "",
            "## Privatësia",
            "",
            "U mblodhën vetëm informacione publike zyrtare. Faqet e rezultateve dhe listave të "
            "studentëve përjashtohen me pattern-et `rezultatet`, `rezultati` dhe `listat`. "
            "Emrat dhe kontaktet e stafit publik janë informacion zyrtar dhe lejohen.",
            "",
            "## PDF që kërkuan OCR",
            "",
        ]
        if self.stats.ocr_pdfs:
            lines.extend(f"- {url}" for url in self.stats.ocr_pdfs)
        else:
            lines.append("Asnjë.")
        lines.extend(["", "## Lidhje Google Drive të pandjekura", ""])
        if self.stats.drive_links:
            lines.extend(f"- {url}" for url in self.stats.drive_links)
        else:
            lines.append("Asnjë.")
        lines.extend(["", "## Dublikatë të sakta", ""])
        if self.stats.duplicates:
            lines.extend(f"- {url} (identik me {original})" for url, original in self.stats.duplicates)
        else:
            lines.append("Asnjë.")
        lines.extend(["", "## URL të anashkaluara për privatësi", ""])
        if self.stats.privacy_skipped:
            lines.extend(f"- {url}" for url in self.stats.privacy_skipped)
        else:
            lines.append("Asnjë.")
        lines.extend(["", "## Lajme dhe dokumente të përjashtuara", ""])
        if self.stats.old_news_skipped or self.stats.internal_skipped or self.stats.generic_skipped:
            lines.extend(f"- Lajm i vjetër ose pa datë: {url}" for url in self.stats.old_news_skipped)
            lines.extend(f"- Dokument i brendshëm: {url}" for url in self.stats.internal_skipped)
            lines.extend(f"- Titull gjenerik: {url}" for url in self.stats.generic_skipped)
        else:
            lines.append("Asnjë.")
        lines.extend(["", "## Versione rregulloresh të zëvendësuara", ""])
        if self.stats.versions_removed:
            lines.extend(f"- {old} → {newest}" for old, newest in self.stats.versions_removed)
        else:
            lines.append("Asnjë.")
        lines.extend(["", "## Dështime", ""])
        if self.stats.failures:
            lines.extend(f"- {url}: {reason}" for url, reason in self.stats.failures)
        else:
            lines.append("Asnjë.")
        lines.extend(["", "## URL që munguan në këtë run", ""])
        if self.stats.disappeared:
            lines.extend(f"- {url}" for url in self.stats.disappeared)
        else:
            lines.append("Asnjë ose crawl-i u ndal para se të kontrollohej e gjithë radha.")
        return "\n".join(lines) + "\n"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def crawl_paths() -> tuple[Path, Path, Path]:
    data_dir = Path(settings.upload_dir).parent
    return data_dir / "crawl_manifest.json", data_dir / "crawl_report.md", Path(settings.upload_dir)


def run_crawl(config_path: Path, max_pages: int | None = None, dry_run: bool = False) -> CrawlStats:
    config = CrawlConfig.from_file(config_path)
    manifest_path, report_path, upload_dir = crawl_paths()
    crawler = Crawler(
        config,
        manifest_path=manifest_path,
        report_path=report_path,
        upload_dir=upload_dir,
        dry_run=dry_run,
        max_pages=max_pages,
    )
    stats = crawler.run()
    if not dry_run:
        print(f"Raport: {report_path}")
    return stats
