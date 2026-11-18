import threading
import time

import pytest

from app import jobs


def wait(job_id, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        job = jobs.get_job(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("puna nuk përfundoi")


def test_job_runs_and_keeps_log():
    job = jobs.start_job("test", lambda log: (log("hapi 1"), log("hapi 2"), 42)[-1])
    done = wait(job["id"])
    assert done["status"] == "done" and done["result"] == 42
    assert done["log"] == ["hapi 1", "hapi 2"]


def test_failed_job_reports_error():
    def boom(log):
        raise ValueError("shkarkimi dështoi")

    done = wait(jobs.start_job("test", boom)["id"])
    assert done["status"] == "failed"
    assert "shkarkimi dështoi" in done["log"][-1]


def test_only_one_job_at_a_time():
    release = threading.Event()
    first = jobs.start_job("test", lambda log: release.wait(5))
    with pytest.raises(RuntimeError):
        jobs.start_job("test", lambda log: None)
    release.set()
    wait(first["id"])
    wait(jobs.start_job("test", lambda log: None)["id"])  # pas përfundimit lejohet përsëri
