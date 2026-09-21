"""Concurrency pool + rate limiting for diagnose jobs.

Default concurrency=1 preserves sequential behavior.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class RateLimiter:
    """Simple global min-interval limiter (thread-safe)."""

    def __init__(self, rpm: float | None = None):
        self.min_interval = (60.0 / rpm) if rpm and rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._next_ok = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next_ok - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next_ok = now + self.min_interval


def map_pool(
    items: Iterable[T],
    fn: Callable[[T], R],
    *,
    concurrency: int = 1,
    rate_limiter: RateLimiter | None = None,
) -> list[R]:
    """Map fn over items with optional thread pool.

    concurrency <= 1 → sequential (stable default).
    Results returned in input order.
    """
    seq = list(items)
    if not seq:
        return []
    workers = max(1, int(concurrency))

    def _call(item: T) -> R:
        if rate_limiter is not None:
            rate_limiter.wait()
        return fn(item)

    if workers == 1:
        return [_call(x) for x in seq]

    results: list[R | None] = [None] * len(seq)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_call, item): i for i, item in enumerate(seq)}
        for fut in as_completed(futs):
            i = futs[fut]
            results[i] = fut.result()
    return [r for r in results if r is not None]  # type: ignore[misc]
