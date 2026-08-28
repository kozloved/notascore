from dotenv import load_dotenv

load_dotenv()

import os
import sys

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


if __name__ == "__main__":
    database.init_db()

    redis_client = Redis.from_url(REDIS_URL)
    worker_cls = SimpleWorker if sys.platform == "darwin" else Worker

    print("Starting NotaScore Transcription Engine worker")
    print(f"Queue: {QUEUE_NAME}")
    print(f"Redis: {REDIS_URL}")
    print(f"Worker: {worker_cls.__name__}")

    worker = worker_cls([QUEUE_NAME], connection=redis_client)
    worker.work()
