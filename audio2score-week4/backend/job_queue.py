from dotenv import load_dotenv

load_dotenv()

import os
import redis
from rq import Queue

from tasks import process_job

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
QUEUE_NAME = os.getenv("QUEUE_NAME", "transcription")

redis_client = redis.from_url(REDIS_URL)

task_queue = Queue(
    QUEUE_NAME,
    connection=redis_client,
)


def enqueue_job(job_id: str):
    return task_queue.enqueue(
        process_job,
        job_id,
        job_timeout=600,
        result_ttl=86400,
    )
