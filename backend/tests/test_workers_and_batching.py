from datetime import UTC, datetime, timedelta

from app.services.payout_batcher import make_sender_batch_id, should_fire
from app.workers.payout_worker import MAX_BACKOFF_SECONDS, next_delay

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_should_fire():
    kw = dict(min_items=10, max_wait_seconds=3600, now=NOW)
    assert not should_fire(0, None, **kw)
    assert should_fire(10, None, **kw)
    assert not should_fire(3, NOW - timedelta(minutes=5), **kw)
    assert should_fire(3, NOW - timedelta(hours=2), **kw)
    assert not should_fire(3, None, **kw)


def test_sender_batch_id_unique_and_short():
    ids = {make_sender_batch_id(NOW) for _ in range(50)}
    assert len(ids) == 50
    assert all(i.startswith("SQ-20260101000000-") and len(i) <= 30 for i in ids)


def test_backoff():
    assert next_delay(30, 0) == 30
    assert next_delay(30, 1) == 60
    assert next_delay(30, 2) == 120
    assert next_delay(30, 50) == MAX_BACKOFF_SECONDS
