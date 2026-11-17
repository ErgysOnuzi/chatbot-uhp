"""Modelet e bazës së të dhënave."""

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import settings
from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    """Një dokument zyrtar i ngarkuar nga administrata (rregullore, orar, procedurë)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(Base):
    """Një pjesë e vogël teksti nga dokumenti, me vektorin e saj (embedding)."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))

    document: Mapped[Document] = relationship(back_populates="chunks")


class Conversation(Base):
    """Një bisedë e një studenti (pa të dhëna personale)."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    """Një mesazh në bisedë: pyetja e studentit ose përgjigjja e chatbot-it."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" ose "assistant"
    content: Mapped[str] = mapped_column(Text)
    # Vetëm për përgjigjet: pyetja të cilës i përgjigjet, a u gjet përgjigje, burimet, vlerësimi
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered: Mapped[bool] = mapped_column(Boolean, default=True)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    feedback: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 1 ose -1
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
