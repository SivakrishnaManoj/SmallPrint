"""Simple in-memory per-install rate limiter: 60 requests per 10 minutes."""
from __future__ import annotations
import time
from collections import deque
from threading import Lock

_WINDOW_SECONDS = 600
_MAX_REQUESTS = 60

_buckets: dict[str, deque[float]] = {}
_lock = Lock()


def check(install_id: str) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS
    with _lock:
        if install_id not in _buckets:
            _buckets[install_id] = deque()
        bucket = _buckets[install_id]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _MAX_REQUESTS:
            return False
        bucket.append(now)
        return True
