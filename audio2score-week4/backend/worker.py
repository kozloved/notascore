from dotenv import load_dotenv

load_dotenv()

import os
from redis import Redis
from rq import Worker

import database

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
QUEUE_NAME = os.getenv("QUEUE_NAME", "transcription")


if __name__ == "__main__":
    database.init_db()

    redis_client = Redis.from_url(REDIS_URL)

    print("Starting NotaScore Transcription Engine worker")
    print(f"Queue: {QUEUE_NAME}")
    print(f"Redis: {REDIS_URL}")

    worker = Worker([QUEUE_NAME], connection=redis_client)
    worker.work()
