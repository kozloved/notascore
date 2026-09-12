from dotenv import load_dotenv

load_dotenv()

import os
import sys
import threading
import time

# Basic Pitch / ONNX pull in Objective-C frameworks. RQ's default forked
# work-horse then dies on macOS with objc_initializeAfterForkError.
if sys.platform == "darwin":
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

from redis import Redis
from rq import SimpleWorker, Worker

import database
from redis_config import redis_url

REDIS_URL = redis_url()
QUEUE_NAME = os.getenv("QUEUE_NAME", "transcription")


def _recovery_interval_seconds() -> float:
    raw = os.getenv("JOB_RECOVERY_INTERVAL_SECONDS", "60")
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return 60.0


def _enqueue(job_id: str, delay_seconds: int = 0):
    from job_queue import enqueue_job

    return enqueue_job(job_id, delay_seconds=delay_seconds)


def run_recovery_once():
    actions = database.recover_expired_leases(enqueue=_enqueue)
    try:
        import storage as storage_service
        from lifecycle import sweep_artifact_gc

        sweep_artifact_gc(storage_service.get_storage())
    except Exception as exc:
        print(f"[recovery] artifact sweep skipped: {exc}", flush=True)
    return actions


def _recovery_loop(stop_event: threading.Event):
    while not stop_event.wait(_recovery_interval_seconds()):
        try:
            actions = run_recovery_once()
            if actions:
                print(f"[recovery] processed {len(actions)} lease(s)", flush=True)
        except Exception as exc:
            print(f"[recovery] scan failed: {exc}", flush=True)


if __name__ == "__main__":
    database.init_db()

    redis_client = Redis.from_url(REDIS_URL)
    worker_cls = SimpleWorker if sys.platform == "darwin" else Worker

    print("Starting NotaScore Transcription Engine worker")
    print(f"Queue: {QUEUE_NAME}")
    print(f"Redis: {REDIS_URL}")
    print(f"Worker: {worker_cls.__name__}")
    from adapters.mt3_backend import mt3_available
    from engine.flags import log_pipeline_configuration

    log_pipeline_configuration(mt3_configured=mt3_available())

    stop = threading.Event()
    recovery = threading.Thread(
        target=_recovery_loop,
        args=(stop,),
        name="lease-recovery",
        daemon=True,
    )
    recovery.start()
    try:
        run_recovery_once()
    except Exception as exc:
        print(f"[recovery] initial scan failed: {exc}", flush=True)

    worker = worker_cls([QUEUE_NAME], connection=redis_client)
    try:
        worker.work()
    finally:
        stop.set()
