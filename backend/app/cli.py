"""Ngarkimi i dokumenteve pa panel.

Përdorimi:
    python -m app.cli ingest ../docs/universiteti --category "Universiteti"
    python -m app.cli fetch-official ../docs/universiteti/burimet-zyrtare.json

Nëse një dokument me të njëjtin titull ekziston, zëvendësohet (komanda mund të përsëritet).
"""

import argparse
import json
import shutil
import urllib.request
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .chunking import SUPPORTED_EXTENSIONS
from .config import settings
from .db import SessionLocal, init_db
from .models import Document
from .rag import ingest_file


def _title_from_markdown(path: Path) -> str:
    if path.suffix.lower() == ".md":
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return path.stem.replace("_", " ").replace("-", " ").strip().capitalize()


def _replace_existing(db: Session, title: str) -> None:
    for old in db.scalars(select(Document).where(Document.title == title)).all():
        (Path(settings.upload_dir) / old.filename).unlink(missing_ok=True)
        db.delete(old)
    db.commit()


def _ingest_one(db: Session, source: Path, title: str, category: str | None) -> None:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / f"{uuid.uuid4().hex}{source.suffix.lower()}"
    shutil.copy(source, stored)
    try:
        _replace_existing(db, title)
        document = ingest_file(db, stored, title, stored.name, category)
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
            _ingest_one(db, target, item["title"], item.get("category"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Mjete për chatbot-in")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ngarko të gjithë dokumentet nga një dosje")
    ingest.add_argument("folder", type=Path)
    ingest.add_argument("--category", default=None)

    official = sub.add_parser("fetch-official", help="Shkarko dhe ngarko PDF-të zyrtare nga lista JSON")
    official.add_argument("sources", type=Path)

    args = parser.parse_args()
    if args.command == "ingest":
        ingest_folder(args.folder, args.category)
    elif args.command == "fetch-official":
        fetch_official(args.sources)


if __name__ == "__main__":
    main()
