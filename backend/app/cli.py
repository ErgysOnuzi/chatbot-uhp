"""Ngarkimi i dokumenteve pa panel.

Përdorimi:
    python -m app.cli ingest ../docs/universiteti --category "Universiteti"
    python -m app.cli fetch-official ../docs/universiteti/burimet-zyrtare.json
    python -m app.cli test-llm
    python -m app.cli crawl --config ../docs/universiteti/crawl.json [--max-pages 400] [--dry-run]
    python -m app.cli prune-excluded --config ../docs/universiteti/crawl.json [--apply]

Nëse një dokument me të njëjtin titull ekziston, zëvendësohet (komanda mund të përsëritet).
"""

import argparse
import json
import shutil
import urllib.request
import uuid
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .chunking import SUPPORTED_EXTENSIONS
from .config import settings
from .crawler import CrawlConfig, URLFilter, is_internal_document, run_crawl
from .db import SessionLocal, init_db
from .models import Document
from .rag import ingest_file


def _title_from_markdown(path: Path) -> str:
    if path.suffix.lower() == ".md":
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return path.stem.replace("_", " ").replace("-", " ").strip().capitalize()


def _replace_existing(db: Session, title: str, source_url: str | None = None) -> None:
    """Fshin versionin e mëparshëm: me të njëjtin titull ose nga e njëjta adresë (p.sh. nga crawler-i)."""
    condition = Document.title == title
    if source_url:
        condition = or_(condition, Document.source_url == source_url)
    for old in db.scalars(select(Document).where(condition)).all():
        (Path(settings.upload_dir) / old.filename).unlink(missing_ok=True)
        db.delete(old)
    db.commit()


def _ingest_one(
    db: Session,
    source: Path,
    title: str,
    category: str | None,
    source_url: str | None = None,
) -> None:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / f"{uuid.uuid4().hex}{source.suffix.lower()}"
    shutil.copy(source, stored)
    try:
        _replace_existing(db, title, source_url)
        document = ingest_file(db, stored, title, stored.name, category, source_url=source_url)
        print(f"OK     {title}: {len(document.chunks)} pjesë")
    except ValueError as exc:
        stored.unlink(missing_ok=True)
        print(f"GABIM  {title}: {exc}")


def ingest_folder(folder: Path, category: str | None) -> None:
    init_db()
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not files:
        print(f"Nuk u gjet asnjë dokument në {folder}")
        return
    with SessionLocal() as db:
        for path in files:
            _ingest_one(db, path, _title_from_markdown(path), category)


def fetch_official(sources_file: Path) -> None:
    """Shkarkon PDF-të zyrtare nga faqja e universitetit dhe i ngarkon (me OCR kur duhet)."""
    init_db()
    sources = json.loads(sources_file.read_text(encoding="utf-8"))
    download_dir = Path(settings.upload_dir).parent / "zyrtare"
    download_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        for item in sources:
            target = download_dir / Path(item["url"]).name
            if not target.exists():
                print(f"Duke shkarkuar: {item['title']}")
                request = urllib.request.Request(item["url"], headers={"User-Agent": "chatbot-uhp/0.1"})
                try:
                    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:
                        shutil.copyfileobj(response, out)
                except Exception as exc:
                    target.unlink(missing_ok=True)
                    print(f"GABIM  {item['title']}: shkarkimi dështoi ({exc})")
                    continue
            _ingest_one(db, target, item["title"], item.get("category"), item["url"])


def prune_excluded(config_path: Path, apply: bool) -> None:
    """Gjen dokumentet në bazë që rregullat aktuale të crawl.json i përjashtojnë dhe, me --apply, i fshin.

    Përdoret pas ndryshimit të rregullave (p.sh. dokumentet e shfuqizuara), sepse crawler-i
    vetë nuk fshin asgjë që është ngarkuar më parë.
    """
    init_db()
    url_filter = URLFilter(CrawlConfig.from_file(config_path))
    with SessionLocal() as db:
        documents = db.scalars(select(Document).where(Document.source_url.is_not(None))).all()
        to_delete = []
        for document in documents:
            decision = url_filter.classify(document.source_url)
            if decision.kind == "skip" or is_internal_document(document.source_url, document.title):
                to_delete.append((document, decision.reason or "dokument i brendshëm"))
        for document, reason in to_delete:
            print(f"{'FSHIHET' if apply else 'do fshihej'}  [{reason}]  {document.title}  <{document.source_url}>")
            if apply:
                (Path(settings.upload_dir) / document.filename).unlink(missing_ok=True)
                db.delete(document)
        if apply:
            db.commit()
        print(f"\n{len(to_delete)} dokumente {'u fshinë' if apply else 'do të fshiheshin; nise përsëri me --apply për t' + chr(39) + 'i fshirë'}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mjete për Asistentin e Studentëve")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ngarko të gjithë dokumentet nga një dosje")
    ingest.add_argument("folder", type=Path)
    ingest.add_argument("--category", default=None)

    sub.add_parser("test-llm", help="Provo lidhjen me modelin gjuhësor dhe shfaq çfarë kthen")

    official = sub.add_parser("fetch-official", help="Shkarko dhe ngarko PDF-të zyrtare nga lista JSON")
    official.add_argument("sources", type=Path)

    prune = sub.add_parser("prune-excluded", help="Fshi dokumentet që rregullat e crawl.json i përjashtojnë")
    prune.add_argument("--config", required=True, type=Path)
    prune.add_argument("--apply", action="store_true", help="Pa këtë vetëm shfaqet lista")

    crawl = sub.add_parser("crawl", help="Gjej dhe ngarko faqet dhe dokumentet publike")
    crawl.add_argument("--config", required=True, type=Path)
    crawl.add_argument("--max-pages", type=int, default=None)
    crawl.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "ingest":
        ingest_folder(args.folder, args.category)
    elif args.command == "fetch-official":
        fetch_official(args.sources)
    elif args.command == "test-llm":
        from .llm import diagnose

        print(json.dumps(diagnose(), ensure_ascii=False, indent=2, default=str))
    elif args.command == "prune-excluded":
        prune_excluded(args.config, args.apply)
    elif args.command == "crawl":
        run_crawl(args.config, max_pages=args.max_pages, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
