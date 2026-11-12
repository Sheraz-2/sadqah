"""Payout worker: turns queued micro-grants into PayPal batch payouts.

    python -m app.workers.payout_worker

Each cycle calls `services.payout_batcher.run_once` (fire when enough grants are queued or the oldest has waited long
enough, submit due retries, recover crashed batches). The loop never dies on one bad cycle: it logs the error TYPE (never
payload, handles or amounts of a person) and backs off. SIGTERM / SIGINT finish the current cycle and exit cleanly.
Nothing runs at import time; only the "worker" database role is opened.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from app.core.config import get_settings
from app.core.crypto import get_crypto
from app.core.db import Database
from app.services import payout_batcher
from app.services.paypal_client import PayPalClient

log = logging.getLogger("sadqah.payout_worker")

MAX_BACKOFF_SECONDS = 300


def next_delay(base_seconds: float, consecutive_failures: int) -> float:
    """Normal cadence after success; doubling (capped) after consecutive failed cycles."""
    if consecutive_failures <= 0:
        return float(base_seconds)
    return float(min(MAX_BACKOFF_SECONDS, base_seconds * (2 ** min(consecutive_failures, 6))))


async def wait_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


def install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # e.g. Windows: Ctrl+C still raises KeyboardInterrupt
            pass


async def run_loop(cycle: Callable[[], Awaitable[None]], stop: asyncio.Event, base_seconds: float, name: str,
                   sleep: Callable[[asyncio.Event, float], Awaitable[None]] = wait_or_stop) -> None:
    failures = 0
    while not stop.is_set():
        try:
            await cycle()
            failures = 0
        except Exception as exc:  # keep the worker alive; the next cycle retries
            failures += 1
            log.error("%s cycle failed (%s), %d in a row", name, type(exc).__name__, failures)
        await sleep(stop, next_delay(base_seconds, failures))


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    crypto = get_crypto()
    db = await Database(settings).open(["worker"])
    paypal = PayPalClient(settings)
    stop = asyncio.Event()
    install_signal_handlers(stop)

    async def cycle() -> None:
        for outcome in await payout_batcher.run_once(db, paypal, crypto, settings):
            log.info("batch %s: %s (sent %d, rejected %d) %s", outcome.batch_id, outcome.status, outcome.items_sent,
                     outcome.items_rejected, outcome.detail[:200])

    log.info("payout worker started (poll %ss)", settings.payout_poll_seconds)
    try:
        await run_loop(cycle, stop, settings.payout_poll_seconds, "payout")
    finally:
        await paypal.aclose()
        await db.close()
        log.info("payout worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
