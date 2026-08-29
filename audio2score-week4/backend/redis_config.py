"""Redis connection URL for Docker Compose (and optional host overrides).

Prefer REDIS_PRIVATE_URL when a host injects an internal URL; otherwise REDIS_URL.
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
