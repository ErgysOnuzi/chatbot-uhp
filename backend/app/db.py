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
