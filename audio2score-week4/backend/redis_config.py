"""Redis connection URL for local Compose and Render.

Prefer REDIS_PRIVATE_URL when a host injects an internal URL; otherwise
REDIS_URL (Render Key Value connectionString).
"""

from __future__ import annotations

import os

DEFAULT_REDIS_URL = "redis://localhost:6379"


def redis_url() -> str:
    return (
        os.getenv("REDIS_PRIVATE_URL")
        or os.getenv("REDIS_URL")
        or DEFAULT_REDIS_URL
    ).strip()
