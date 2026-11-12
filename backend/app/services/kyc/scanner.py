"""Malware scan hook. Speaks the ClamAV `INSTREAM` protocol to a clamd daemon (CLAMAV_HOST / CLAMAV_PORT).

Without clamd the file has still been fully re-encoded or rebuilt at upload (see upload_validation.py), which removes
most active content, but a production deployment should run clamd and set CLAMAV_HOST so this check is real.
"""
from __future__ import annotations

import asyncio
import struct

from app.core.config import Settings


async def scan_bytes(settings: Settings, data: bytes) -> str:
    """Returns 'clean', 'infected' or 'failed'."""
    if not settings.clamav_host:
        return "clean"
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(settings.clamav_host, settings.clamav_port), 5)
        try:
            writer.write(b"zINSTREAM\0")
            for i in range(0, len(data), 64 * 1024):
                chunk = data[i : i + 64 * 1024]
                writer.write(struct.pack("!I", len(chunk)) + chunk)
            writer.write(struct.pack("!I", 0))
            await writer.drain()
            reply = (await asyncio.wait_for(reader.read(1024), 30)).decode(errors="replace")
        finally:
            writer.close()
    except (OSError, asyncio.TimeoutError):
        return "failed"
    if "FOUND" in reply:
        return "infected"
    return "clean" if "OK" in reply else "failed"
