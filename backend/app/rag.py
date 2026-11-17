"""Retrieval-Augmented Generation: gjen pjesët relevante dhe ndërton kërkesën për LLM."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .chunking import chunk_text, clean_text, extract_text
from .config import settings
from .embeddings import embed, embed_one
from .models import Chunk, Document
from .sources import select_sources

NO_ANSWER = (
    "Më vjen keq, këtë informatë nuk e gjeta në dokumentet zyrtare të universitetit. "
    "Ju lutem kontaktoni administratën e fakultetit për më shumë detaje."
)
# Fjalia e parë e NO_ANSWER përdoret për të dalluar kur modeli nuk e di përgjigjen.
NO_ANSWER_MARK = "këtë informatë nuk e gjeta"

SYSTEM_PROMPT = f"""Ti je asistenti virtual i Universitetit "Ukshin Hoti" Prizren.
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
"""


def ingest_file(db: Session, path: Path, title: str, filename: str, category: str | None = None) -> Document:
    text = clean_text(extract_text(path))
    if not text:
        raise ValueError("Dokumenti nuk ka tekst që mund të lexohet (ndoshta është PDF i skanuar).")
    pieces = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    # Titulli i shtohet secilës pjesë që kërkimi të dijë nga cili dokument vjen.
    vectors = embed([f"{title}\n{piece}" for piece in pieces])

    document = Document(title=title, filename=filename, category=category)
    document.chunks = [
        Chunk(position=i, content=piece, embedding=vector)
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
    query_vector = embed_one(query)
    distance = Chunk.embedding.cosine_distance(query_vector).label("distance")
    rows = db.execute(
        select(Chunk, distance)
        .options(joinedload(Chunk.document))
        .order_by(distance)
        .limit(settings.top_k)
    ).all()
    return [(chunk, float(dist)) for chunk, dist in rows if dist <= settings.max_distance]


def build_messages(question: str, hits: list[tuple[Chunk, float]], history: list[dict]) -> list[dict]:
    context = "\n\n---\n\n".join(
        f"[{i + 1}] Dokumenti: {chunk.document.title}\n{chunk.content}" for i, (chunk, _) in enumerate(hits)
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
        [(chunk.document_id, chunk.document.title, distance) for chunk, distance in hits],
        settings.source_margin,
        settings.max_sources,
    )
