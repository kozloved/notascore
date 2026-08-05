from dotenv import load_dotenv

load_dotenv()

import os
from redis import Redis
from rq import Worker, Connection

import database

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
QUEUE_NAME = os.getenv("QUEUE_NAME", "transcription")


if __name__ == "__main__":
    database.init_db()

    redis_client = Redis.from_url(REDIS_URL)

    print(f"Starting Audio2Score Week 4 worker")
    print(f"Queue: {QUEUE_NAME}")
    print(f"Redis: {REDIS_URL}")

    with Connection(redis_client):
        worker = Worker([QUEUE_NAME])
        worker.work()
