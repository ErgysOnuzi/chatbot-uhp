"""Retrieval-Augmented Generation: gjen pjesët relevante dhe ndërton kërkesën për LLM."""

from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.orm import Session, joinedload

from .chunking import chunk_text, clean_text, extract_text
from .config import settings
from .embeddings import embed, embed_one
from .models import Chunk, Document
from .search import fold, is_stale, matched_terms, news_date_from_text, query_terms, rrf, to_tsquery, upload_date
from .sources import select_sources

NO_ANSWER = (
    "Më vjen keq, këtë informatë nuk e gjeta në dokumentet zyrtare të universitetit. "
    "Ju lutem kontaktoni administratën e fakultetit për më shumë detaje."
)
# Fjalia e parë e NO_ANSWER përdoret për të dalluar kur modeli nuk e di përgjigjen.
NO_ANSWER_MARK = "këtë informatë nuk e gjeta"

SYSTEM_PROMPT = f"""Ti je Asistenti i Studentëve i Universitetit "Ukshin Hoti" Prizren.
Detyra jote është t'u përgjigjesh studentëve për provimet, oraret, afatet, procedurat
administrative, diplomimin dhe informata të tjera të universitetit.

Rregullat:
1. Përgjigju VETËM duke u bazuar në "Kontekstin nga dokumentet zyrtare" që të jepet.
2. Mos shpik data, afate, emra, numra apo procedura që nuk janë në kontekst.
3. Nëse përgjigjja nuk gjendet në kontekst, përgjigju saktësisht me:
   "{NO_ANSWER}"
4. Shkruaj në gjuhën shqipe standarde, qartë dhe shkurt.
5. Kur procedura ka disa hapa, jepi si listë me numra.
6. Mos kërko dhe mos ruaj të dhëna personale të studentëve.
7. Nëse dokumentet japin informata të ndryshme për të njëjtën gjë, mbështetu te dokumenti me datën
   më të re dhe përmende datën. Për afate dhe njoftime, thuaj nga cila datë është informata.
"""


def ingest_file(
    db: Session,
    path: Path,
    title: str,
    filename: str,
    category: str | None = None,
    source_url: str | None = None,
    max_ocr_pages: int | None = None,
    published_at: date | None = None,
    is_news: bool = False,
) -> Document:
    text = clean_text(extract_text(path, max_ocr_pages=max_ocr_pages))
    if not text:
        raise ValueError("Dokumenti nuk ka tekst që mund të lexohet (ndoshta është PDF i skanuar).")
    pieces = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    # Titulli i shtohet secilës pjesë që kërkimi të dijë nga cili dokument vjen.
    vectors = embed([f"{title}\n{piece}" for piece in pieces])

    news_date = news_date_from_text(text)
    document = Document(
        title=title,
        filename=filename,
        category=category,
        source_url=source_url,
        published_at=published_at or news_date or upload_date(source_url),
        is_news=is_news or news_date is not None,
    )
    document.chunks = [
        Chunk(position=i, content=piece, embedding=vector, search_text=fold(piece))
        for i, (piece, vector) in enumerate(zip(pieces, vectors))
    ]
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def retrieval_query(question: str, history: list[dict]) -> str:
    """Për pyetjet vijuese ("po afati?") shtohet pyetja e mëparshme që kërkimi të ketë kontekst."""
    previous = [m["content"] for m in history if m["role"] == "user"]
    if previous and len(question.split()) < 8:
        return f"{previous[-1]}\n{question}"
    return question


def retrieve(db: Session, query: str) -> list[tuple[Chunk, float]]:
    """Kërkim hibrid: semantik (pgvector) + fjalë kyçe (full-text), të bashkuara me RRF.

    Një pjesë përdoret si kontekst nëse është semantikisht afër pyetjes (distanca <= MAX_DISTANCE)
    ose nëse përmban të paktën dy terma të ndryshëm të pyetjes. Lajmet më të vjetra se një vit
    nuk përdoren, që chatbot-i të mos përgjigjet me informata të vjetruara.
    """
    query_vector = embed_one(query)
    distance = Chunk.embedding.cosine_distance(query_vector).label("distance")
    cutoff = date.today() - timedelta(days=settings.news_max_age_days)
    fresh = or_(Document.is_news.is_(False), Document.published_at >= cutoff)
    pool = settings.candidate_pool

    vector_rows = db.execute(
        select(Chunk, distance).join(Chunk.document).options(joinedload(Chunk.document))
        .where(fresh).order_by(distance).limit(pool)
    ).all()

    keyword_rows = []
    terms = query_terms(query)
    tsquery = to_tsquery(terms)
    if tsquery and settings.hybrid_search:
        simple = literal_column("'simple'::regconfig")
        ts = func.to_tsquery(simple, tsquery)
        vector_col = func.to_tsvector(simple, func.coalesce(Chunk.search_text, literal_column("''")))
        rank = func.ts_rank_cd(vector_col, ts).label("rank")
        keyword_rows = db.execute(
            select(Chunk, distance, rank).join(Chunk.document).options(joinedload(Chunk.document))
            .where(fresh, vector_col.op("@@")(ts)).order_by(rank.desc()).limit(pool)
        ).all()

    chunks: dict[int, tuple[Chunk, float]] = {}
    for row in [*vector_rows, *keyword_rows]:
        chunks[row[0].id] = (row[0], float(row[1]))
    fused = rrf([[r[0].id for r in vector_rows], [r[0].id for r in keyword_rows]])

    today = date.today()
    hits: list[tuple[Chunk, float]] = []
    for chunk_id in fused:
        chunk, dist = chunks[chunk_id]
        if is_stale(chunk.document.is_news, chunk.document.published_at, today, settings.news_max_age_days):
            continue
        strong_keywords = matched_terms(terms, chunk.search_text or fold(chunk.content)) >= 2
        if dist <= settings.max_distance or strong_keywords:
            hits.append((chunk, dist))
        if len(hits) >= settings.top_k:
            break
    if not hits:
        return []
    # Pjesët e gjetura me fjalë kyçe por me distancë të madhe trajtohen si të forta për zgjedhjen e burimeve.
    best = min(dist for _, dist in hits)
    return [(chunk, min(dist, best) if dist > settings.max_distance else dist) for chunk, dist in hits]


def build_messages(question: str, hits: list[tuple[Chunk, float]], history: list[dict]) -> list[dict]:
    def label(chunk: Chunk) -> str:
        published = chunk.document.published_at
        if published is None:
            return chunk.document.title
        kind = "publikuar" if chunk.document.is_news else "data e dokumentit"
        return f"{chunk.document.title} ({kind}: {published.strftime('%d.%m.%Y')})"

    context = "\n\n---\n\n".join(
        f"[{i + 1}] Dokumenti: {label(chunk)}\n{chunk.content}" for i, (chunk, _) in enumerate(hits)
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-6:])
    messages.append(
        {
            "role": "user",
            "content": f"Konteksti nga dokumentet zyrtare:\n\n{context}\n\nPyetja e studentit: {question}",
        }
    )
    return messages


def sources_from(hits: list[tuple[Chunk, float]]) -> list[dict]:
    return select_sources(
        [(chunk.document_id, chunk.document.title, distance, chunk.document.source_url) for chunk, distance in hits],
        settings.source_margin,
        settings.max_sources,
    )
