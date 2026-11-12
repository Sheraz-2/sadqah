import uuid

from app.services.kyc import liveness
from app.services.kyc.requirements import missing_requirements

USER = uuid.uuid4()


def test_liveness_round_trip(crypto):
    ch = liveness.issue(crypto, USER, now=1000)
    assert len(ch.code) == 4 and ch.code.isdigit()
    assert liveness.verify(crypto, ch.token, USER, now=1000 + 60) == ch.code


def test_liveness_rejects_expired_foreign_and_forged(crypto):
    ch = liveness.issue(crypto, USER, now=1000)
    assert liveness.verify(crypto, ch.token, USER, now=1000 + liveness.TTL_SECONDS + 1) is None
    assert liveness.verify(crypto, ch.token, uuid.uuid4(), now=1001) is None
    payload, sig = ch.token.split(".")
    assert liveness.verify(crypto, payload + "." + sig[:-2] + "AA", USER, now=1001) is None
    for junk in ["", "x", "a.b", "....", "é.é"]:
        assert liveness.verify(crypto, junk, USER, now=1001) is None


def test_liveness_tokens_differ(crypto):
    assert liveness.issue(crypto, USER).token != liveness.issue(crypto, USER).token


def test_missing_requirements():
    assert missing_requirements(False, []) == [
        "identity_details_and_consent", "national_id_or_passport", "utility_bill", "selfie",
        "bank_statement_or_proof_of_income"]
    docs = [{"doc_type": t, "scan_status": "clean"} for t in ("passport", "utility_bill", "selfie", "proof_of_income")]
    assert missing_requirements(True, docs) == []
    docs[2]["scan_status"] = "infected"
    assert missing_requirements(True, docs) == ["selfie"]
