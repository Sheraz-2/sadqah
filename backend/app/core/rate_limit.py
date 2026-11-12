"""Fixed-window rate limiting. Redis when REDIS_URL is set (required outside dev, so limits are shared
between processes); an in-process dictionary otherwise.

Keys are built from peppered hashes, never from raw IP addresses, e-mails or tokens.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int


class RateLimiter:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis = None
        if redis_url:
            import redis.asyncio as aioredis  # lazy: only needed when configured

            self._redis = aioredis.from_url(redis_url, socket_timeout=1.0, socket_connect_timeout=1.0)
        self._memory: dict[str, tuple[int, int]] = {}
        self._last_sweep = 0.0

    async def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        now = time.time()
        bucket = int(now // window_seconds)
        retry_after = int((bucket + 1) * window_seconds - now) + 1
        if self._redis is not None:
            rkey = f"rl:{key}:{bucket}"
            try:
                pipe = self._redis.pipeline()
                pipe.incr(rkey)
                pipe.expire(rkey, window_seconds + 1)
                count = int((await pipe.execute())[0])
                return Decision(count <= limit, retry_after)
            except Exception:  # noqa: BLE001  (fail open on a Redis outage rather than take donations down)
                return Decision(True, 0)
        self._sweep(now)
        stored_bucket, count = self._memory.get(key, (bucket, 0))
        if stored_bucket != bucket:
            stored_bucket, count = bucket, 0
        count += 1
        self._memory[key] = (stored_bucket, count)
        return Decision(count <= limit, retry_after)

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        if len(self._memory) > 50_000:
            self._memory.clear()

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
