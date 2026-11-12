"""KYC worker: finds applications in status `processing` and runs the AI assessment pipeline on them.

    python -m app.workers.kyc_worker

The pipeline only produces ADVICE; it moves a case to `needs_human_review` and nothing else. If ANTHROPIC_API_KEY is
not set the pipeline still runs: it flags "automatic reading unavailable" and the case waits for a human reviewer.
A case that errors is marked for human review with a neutral reason instead of being retried forever.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.core.config import Settings, get_settings
from app.core.crypto import Crypto, get_crypto
from app.core.db import Database
from app.services.file_vault import FileVault
from app.services.kyc import pipeline
from app.services.kyc.extractor import DocumentExtractor
from app.services.kyc.face_match import get_face_matcher
from app.workers.payout_worker import install_signal_handlers, run_loop

log = logging.getLogger("sadqah.kyc_worker")

_PROCESSING = "SELECT recipient_id FROM core.recipients_kyc WHERE status = 'processing' ORDER BY updated_at LIMIT $1"


async def run_once(db: Database, vault: FileVault, crypto: Crypto, settings: Settings, limit: int = 5) -> int:
    extractor = DocumentExtractor(settings)
    matcher = get_face_matcher(settings, extractor)
    async with db.session("kyc") as conn:
        ids: list[uuid.UUID] = [r["recipient_id"] for r in await conn.fetch(_PROCESSING, limit)]
    done = 0
    for recipient_id in ids:
        try:
            outcome = await pipeline.process_case(db, vault, crypto, settings, extractor, matcher, recipient_id)
        except Exception as exc:  # noqa: BLE001  one bad case must not stop the queue
            log.error("kyc case %s failed (%s); sending it to human review", recipient_id, type(exc).__name__)
            await pipeline.store_failure(db, recipient_id, f"Automatic assessment failed ({type(exc).__name__}).")
            continue
        done += outcome == "assessed"
    return done


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    crypto = get_crypto()
    db = await Database(settings).open(["kyc"])
    vault = FileVault(settings, crypto)
    stop = asyncio.Event()
    install_signal_handlers(stop)

    async def cycle() -> None:
        n = await run_once(db, vault, crypto, settings)
        if n:
            log.info("assessed %d case(s)", n)

    log.info("kyc worker started (poll %ss, AI %s)", settings.kyc_poll_seconds,
             "on" if settings.anthropic_api_key else "off: cases wait for human review")
    try:
        await run_loop(cycle, stop, settings.kyc_poll_seconds, "kyc")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
