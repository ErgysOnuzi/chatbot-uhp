"""Lidhja me bazën e të dhënave."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Krijon zgjerimin pgvector dhe tabelat nëse nuk ekzistojnë."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    from . import models  # noqa: F401  (regjistron modelet)

    Base.metadata.create_all(engine)
    # create_all nuk i ndryshon tabelat ekzistuese, prandaj migrimi bëhet këtu.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url text"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS published_at date"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_news boolean NOT NULL DEFAULT false"))
        conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS search_text text"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chunks_search_text ON chunks "
                "USING gin (to_tsvector('simple', coalesce(search_text, '')))"
            )
        )
    _backfill()


def _backfill() -> None:
    """Plotëson kolonat e reja për dokumentet e ngarkuara para kërkimit hibrid dhe datave."""
    from .search import index_text, news_date_from_text, upload_date

    with engine.begin() as conn:
        # Pjesët pa search_text, si dhe ato me fjalë "anti..." (indeksi i tyre u zgjerua më vonë).
        rows = conn.execute(
            text("SELECT id, content FROM chunks WHERE search_text IS NULL OR content ILIKE '%anti%'")
        ).all()
        for chunk_id, content in rows:
            conn.execute(
                text("UPDATE chunks SET search_text = :t WHERE id = :i"), {"t": index_text(content), "i": chunk_id}
            )

        documents = conn.execute(
            text(
                "SELECT d.id, d.source_url, (SELECT c.content FROM chunks c WHERE c.document_id = d.id "
                "ORDER BY c.position LIMIT 1) FROM documents d WHERE d.published_at IS NULL"
            )
        ).all()
        for document_id, source_url, first_chunk in documents:
            news_date = news_date_from_text(first_chunk or "")
            published = news_date or upload_date(source_url)
            if published:
                conn.execute(
                    text("UPDATE documents SET published_at = :p, is_news = :n WHERE id = :i"),
                    {"p": published, "n": news_date is not None, "i": document_id},
                )
