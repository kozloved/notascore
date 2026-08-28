"""Redis connection URL for local Compose and Railway.

Railway's private network is IPv6. Prefer REDIS_PRIVATE_URL (the
*.railway.internal plugin URL) when it is set.
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
