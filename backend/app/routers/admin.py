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
from .. import jobs

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


# ---------- Punë në sfond: rregulloret zyrtare, pastrimi dhe crawl ----------

IMPORT_HOSTS = ("uni-prizren.com",)


class ImportUrlRequest(BaseModel):
    url: str
    title: str
    category: str | None = None


class PruneRequest(BaseModel):
    apply: bool = False
    config: dict | None = None


class CrawlRequest(BaseModel):
    max_pages: int | None = None
    config: dict | None = None  # nëse mungon, lexohet docs/universiteti/crawl.json


class FetchOfficialRequest(BaseModel):
    sources: list[ImportUrlRequest] | None = None  # nëse mungon, lexohet burimet-zyrtare.json


def _allowed_import_url(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in IMPORT_HOSTS)


def _start(kind, work):
    try:
        return jobs.start_job(kind, work)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/jobs/fetch-official", status_code=202)
def job_fetch_official(req: FetchOfficialRequest | None = None, _: str = Depends(require_admin)):
    """Shkarkon dhe ngarkon rregulloret (nga kërkesa ose nga docs/universiteti/burimet-zyrtare.json)."""
    import json

    from ..cli import fetch_official_items

    if req and req.sources:
        items = [s.model_dump() for s in req.sources]
    else:
        path = settings.docs_path / "universiteti" / "burimet-zyrtare.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Nuk u gjet {path}; dërgoni listën te 'sources'.")
        items = json.loads(path.read_text(encoding="utf-8"))
    bad = [i["url"] for i in items if not _allowed_import_url(i["url"])]
    if bad:
        raise HTTPException(status_code=400, detail=f"Adresa të palejuara: {bad[:3]}")
    return _start("fetch-official", lambda log: fetch_official_items(items, log=log))


@router.post("/jobs/import-url", status_code=202)
def job_import_url(req: ImportUrlRequest, _: str = Depends(require_admin)):
    """Shkarkon dhe ngarkon një dokument nga faqja e universitetit (vetëm uni-prizren.com)."""
    from ..cli import fetch_official_items

    if not _allowed_import_url(req.url):
        raise HTTPException(status_code=400, detail="Lejohen vetëm adresat https të uni-prizren.com.")
    item = {"title": req.title.strip(), "url": req.url, "category": (req.category or "").strip() or None}
    return _start("import-url", lambda log: fetch_official_items([item], log=log))


@router.post("/jobs/crawl", status_code=202)
def job_crawl(req: CrawlRequest, _: str = Depends(require_admin)):
    """Nis crawler-in me docs/universiteti/crawl.json."""
    from ..crawler import run_crawl

    import json
    import tempfile

    if req.config:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(req.config, handle, ensure_ascii=False)
        handle.close()
        config = Path(handle.name)
    else:
        config = settings.docs_path / "universiteti" / "crawl.json"
    if not config.exists():
        raise HTTPException(status_code=404, detail=f"Nuk u gjet {config}; dërgoni konfigurimin te 'config'.")

    def work(log):
        stats = run_crawl(config, max_pages=req.max_pages)
        report = Path(settings.upload_dir).parent / "crawl_report.md"
        try:
            from ..crawler import crawl_paths

            report = crawl_paths()[1]
        except Exception:  # noqa: BLE001
            pass
        if Path(report).exists():
            for line in Path(report).read_text(encoding="utf-8").splitlines()[:150]:
                log(line)
        return str(stats)

    return _start("crawl", work)


@router.post("/prune-excluded")
def prune(req: PruneRequest, _: str = Depends(require_admin)):
    """Liston (ose me apply=true fshin) dokumentet që rregullat e crawl.json i përjashtojnë."""
    from ..cli import prune_excluded

    import json
    import tempfile

    if req.config:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(req.config, handle, ensure_ascii=False)
        handle.close()
        config = Path(handle.name)
    else:
        config = settings.docs_path / "universiteti" / "crawl.json"
    if not config.exists():
        raise HTTPException(status_code=404, detail=f"Nuk u gjet {config}; dërgoni konfigurimin te 'config'.")
    lines: list[str] = []
    result = prune_excluded(config, req.apply, log=lines.append)
    return {"applied": req.apply, "count": len(result), "documents": result}


@router.get("/jobs")
def job_list(_: str = Depends(require_admin)):
    return jobs.list_jobs()


@router.get("/jobs/{job_id}")
def job_status(job_id: str, _: str = Depends(require_admin)):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Puna nuk u gjet.")
    return job
