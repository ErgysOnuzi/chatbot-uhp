"""Logjika e kërkimit hibrid (semantik + fjalë kyçe) dhe e datave, pa varësi nga baza e të dhënave.

Kërkimi semantik (embeddings) i gjen pjesët me kuptim të ngjashëm, por ndonjëherë e humb pjesën
e duhur kur ka shumë dokumente të ngjashme. Kërkimi me fjalë kyçe (full-text në PostgreSQL) i gjen
saktësisht fjalët e pyetjes: kode lëndësh, numra nenesh, emra, "semestri i gjashtë". Të dy listat
bashkohen me Reciprocal Rank Fusion (RRF).
"""

import re
import unicodedata
from datetime import date, timedelta

# Fjalë shumë të shpeshta që nuk ndihmojnë në kërkim (pas heqjes së ë/ç).
STOPWORDS = {
    "a", "e", "i", "te", "se", "ne", "me", "per", "nga", "dhe", "ose", "si", "ku", "kur", "sa", "ka", "kam",
    "jane", "eshte", "esht", "osht", "nje", "qe", "po", "jo", "do", "mund", "duhet", "cili", "cila", "cilat",
    "cilet", "cfare", "qfare", "qka", "cka", "kush", "pse", "si", "ma", "me", "mu", "mi", "une", "ti", "ju",
    "ai", "ajo", "ata", "ato", "im", "ime", "tim", "time", "yt", "jot", "tend", "tende", "tonde", "keto",
    "kjo", "ky", "ate", "atij", "asaj", "deri", "pas", "para", "mbi", "nen", "tek", "te", "edhe", "apo",
    "the", "of", "and", "to", "in", "for", "is", "what", "how", "who", "when", "where",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Numrat rendorë: "semestri i gjashtë" në pyetje, "Semestri 6" në dokument (dhe anasjelltas).
ORDINALS = {
    "pare": "1", "dyte": "2", "trete": "3", "katert": "4", "peste": "5",
    "gjashte": "6", "shtate": "7", "tete": "8", "nente": "9", "dhjete": "10",
}
_ORDINAL_WORDS = {digit: word for word, digit in ORDINALS.items()}


def fold(text: str) -> str:
    """Shkronja të vogla, pa diakritikë (ë→e, ç→c) dhe pa shenja pikësimi."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(_TOKEN_RE.findall(text))


def stem(term: str) -> str:
    """Prerje e thjeshtë e mbaresave (semestri/semestrin/semestrit → semest)."""
    if term.isdigit() or len(term) < 6:
        return term
    return term[: max(4, len(term) - 2)]


def query_terms(query: str) -> list[str]:
    seen: list[str] = []
    for token in fold(query).split():
        if token in STOPWORDS or (len(token) < 2 and not token.isdigit()):
            continue
        for variant in (token, ORDINALS.get(token), _ORDINAL_WORDS.get(token)):
            if variant and variant not in seen:
                seen.append(variant)
    return seen[:14]


def to_tsquery(terms: list[str]) -> str | None:
    """Pyetje për to_tsquery('simple', ...): çdo term si prefiks, të lidhura me OSE."""
    parts = []
    for term in terms:
        root = stem(term)
        parts.append(f"{root}:*" if len(root) >= 3 else root)
    return " | ".join(parts) if parts else None


def matched_terms(terms: list[str], folded_text: str) -> int:
    """Sa terma të ndryshëm të pyetjes gjenden si fillim fjale në tekst."""
    words = folded_text.split()
    count = 0
    for term in terms:
        root = stem(term)
        if any(word.startswith(root) for word in words):
            count += 1
    return count


def rrf(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion: bashkon disa renditje në një, pa pasur nevojë të krahasojë pikët."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores, key=lambda item: (-scores[item], item))


def is_stale(is_news: bool, published_at: date | None, today: date, max_age_days: int = 365) -> bool:
    """Lajmet dhe njoftimet më të vjetra se `max_age_days` (ose pa datë) nuk përdoren si burim."""
    if not is_news:
        return False
    return published_at is None or published_at < today - timedelta(days=max_age_days)


def upload_date(url: str | None) -> date | None:
    """Data e ngarkimit nga adresat e WordPress-it: /wp-content/uploads/2024/11/... → 2024-11-01."""
    if not url:
        return None
    match = re.search(r"/(20\d{2})/(0[1-9]|1[0-2])/", url)
    return date(int(match.group(1)), int(match.group(2)), 1) if match else None


def news_date_from_text(text: str) -> date | None:
    """Crawler-i i shton lajmeve rreshtin "Data e publikimit: YYYY-MM-DD" në fillim."""
    match = re.match(r"\s*Data e publikimit:\s*(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
