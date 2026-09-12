from dotenv import load_dotenv

load_dotenv()

import os
from datetime import timedelta

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


def enqueue_job(job_id: str, job_timeout: int | None = None, delay_seconds: int | None = None):
    timeout = job_timeout or 600
    if delay_seconds and int(delay_seconds) > 0:
        return task_queue.enqueue_in(
            timedelta(seconds=int(delay_seconds)),
            process_job,
            job_id,
            job_timeout=timeout,
            result_ttl=86400,
        )
    return task_queue.enqueue(
        process_job,
        job_id,
        job_timeout=timeout,
        result_ttl=86400,
    )
