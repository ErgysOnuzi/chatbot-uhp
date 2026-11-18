"""Paneli i administratës: kyçja, dokumentet dhe statistikat."""

import secrets
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..chunking import SUPPORTED_EXTENSIONS
from ..config import settings
from ..db import get_db
from ..models import Chunk, Conversation, Document, Message
from ..rag import ingest_file

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginRequest(BaseModel):
    username: str
    password: str


def require_admin(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Duhet të kyçeni.")
    try:
        payload = jwt.decode(authorization[7:], settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sesioni ka skaduar. Kyçuni përsëri.")
    return payload["sub"]


@router.post("/login")
def login(req: LoginRequest):
    valid_user = secrets.compare_digest(req.username.encode(), settings.admin_username.encode())
    valid_pass = secrets.compare_digest(req.password.encode(), settings.admin_password.encode())
    if not (valid_user and valid_pass):
        raise HTTPException(status_code=401, detail="Emri i përdoruesit ose fjalëkalimi është i gabuar.")
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    token = jwt.encode({"sub": req.username, "exp": expires}, settings.jwt_secret, algorithm="HS256")
    return {"token": token}


@router.get("/documents")
def list_documents(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    rows = db.execute(
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
    ).all()
    return [
        {
            "id": doc.id,
            "title": doc.title,
            "filename": doc.filename,
            "category": doc.category,
            "source_url": doc.source_url,
            "chunks": count,
            "created_at": doc.created_at.isoformat(),
        }
        for doc, count in rows
    ]


@router.post("/documents")
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=2, max_length=255),
    category: str | None = Form(default=None, max_length=100),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    original = Path(file.filename or "dokument").name
    suffix = Path(original).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Lejohen vetëm skedarët PDF, DOCX, TXT dhe MD.")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    with stored.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if stored.stat().st_size > settings.max_upload_mb * 1024 * 1024:
        stored.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Skedari është më i madh se {settings.max_upload_mb} MB.")

    try:
        document = ingest_file(db, stored, title.strip(), stored.name, (category or "").strip() or None)
    except ValueError as exc:
        stored.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        stored.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Dokumenti nuk mund të lexohet. Kontrolloni nëse skedari është i dëmtuar.")
    return {"id": document.id, "title": document.title, "chunks": len(document.chunks)}


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokumenti nuk u gjet.")
    (Path(settings.upload_dir) / document.filename).unlink(missing_ok=True)
    db.delete(document)
    db.commit()
    return {"ok": True}


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    total_answers = db.scalar(select(func.count()).where(Message.role == "assistant")) or 0
    unanswered = db.scalar(
        select(func.count()).where(Message.role == "assistant", Message.answered.is_(False))
    ) or 0
    positive = db.scalar(select(func.count()).where(Message.feedback == 1)) or 0
    negative = db.scalar(select(func.count()).where(Message.feedback == -1)) or 0

    recent_unanswered = db.scalars(
        select(Message.question)
        .where(Message.role == "assistant", Message.answered.is_(False), Message.question.is_not(None))
        .order_by(Message.id.desc())
        .limit(20)
    ).all()

    normalized = func.lower(func.trim(Message.content))
    top_questions = db.execute(
        select(normalized.label("q"), func.count().label("n"))
        .where(Message.role == "user")
        .group_by(normalized)
        .order_by(func.count().desc())
        .limit(10)
    ).all()

    return {
        "conversations": db.scalar(select(func.count(Conversation.id))) or 0,
        "questions": total_answers,
        "unanswered": unanswered,
        "answered_rate": round(100 * (total_answers - unanswered) / total_answers, 1) if total_answers else None,
        "feedback_positive": positive,
        "feedback_negative": negative,
        "recent_unanswered": list(recent_unanswered),
        "top_questions": [{"question": q, "count": n} for q, n in top_questions],
    }
