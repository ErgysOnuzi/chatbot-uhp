"""Punë të gjata administrative (shkarkimi i rregulloreve, crawl) që ekzekutohen në sfond.

Punët ekzekutohen një nga një, që të mos shkruajnë njëkohësisht në bazë. Statusi dhe log-u
mbahen në kujtesë dhe lexohen nga paneli i administratës.
"""

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_running = threading.Lock()
MAX_LOG_LINES = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_job(kind: str, work: Callable[[Callable[[str], None]], object]) -> dict:
    """Nis `work(log)` në sfond. Kthen punën; refuzon nëse një punë tjetër është duke punuar."""
    if not _running.acquire(blocking=False):
        raise RuntimeError("Një punë tjetër është duke u ekzekutuar. Prisni sa të përfundojë.")
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "kind": kind, "status": "running", "started_at": _now(), "finished_at": None, "log": [], "result": None}
    with _lock:
        _jobs[job_id] = job

    def log(line: str) -> None:
        logger.info("[%s] %s", kind, line)
        with _lock:
            job["log"].append(str(line))
            if len(job["log"]) > MAX_LOG_LINES:
                del job["log"][: len(job["log"]) - MAX_LOG_LINES]

    def run() -> None:
        try:
            job["result"] = work(log)
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001 - gabimi i shfaqet administratës
            log(f"GABIM: {exc}")
            logger.error(traceback.format_exc())
            job["status"] = "failed"
        finally:
            job["finished_at"] = _now()
            _running.release()

    threading.Thread(target=run, name=f"job-{kind}-{job_id}", daemon=True).start()
    return job_summary(job)


def job_summary(job: dict, tail: int = 200) -> dict:
    with _lock:
        return {**{k: v for k, v in job.items() if k != "log"}, "log": job["log"][-tail:]}


def get_job(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    return job_summary(job) if job else None


def list_jobs() -> list[dict]:
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j["started_at"], reverse=True)[:10]
    return [job_summary(j, tail=5) for j in jobs]
