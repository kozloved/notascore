from dotenv import load_dotenv

load_dotenv()

import os
import redis
from rq import Queue

from redis_config import redis_url
from tasks import process_job

REDIS_URL = redis_url()
QUEUE_NAME = os.getenv("QUEUE_NAME", "transcription")

redis_client = redis.from_url(REDIS_URL)

task_queue = Queue(
    QUEUE_NAME,
    connection=redis_client,
)


def enqueue_job(job_id: str, job_timeout: int | None = None):
    return task_queue.enqueue(
        process_job,
        job_id,
        job_timeout=job_timeout or 600,
        result_ttl=86400,
    )
