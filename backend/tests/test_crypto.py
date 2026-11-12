import pytest

from app.core import aad
from app.core.crypto import Crypto, CryptoError


def test_field_round_trip_and_aad_binding(crypto):
    blob = crypto.encrypt_text("hello", aad.USER_EMAIL)
    assert crypto.decrypt_text(blob, aad.USER_EMAIL) == "hello"
    with pytest.raises(CryptoError):
        crypto.decrypt_text(blob, aad.USER_PHONE)  # copied into another column


def test_message_aad_binds_to_donation(crypto):
    blob = crypto.encrypt_text("thanks", aad.message("d-1"))
    with pytest.raises(CryptoError):
        crypto.decrypt_text(blob, aad.message("d-2"))


def test_tamper_detected(crypto):
    blob = bytearray(crypto.encrypt_text("x", aad.USER_EMAIL))
    blob[-1] ^= 1
    with pytest.raises(CryptoError):
        crypto.decrypt_text(bytes(blob), aad.USER_EMAIL)


def test_old_key_still_decrypts():
    old = Crypto({"k0": bytes(range(1, 33))}, "k0", b"b" * 32, b"p" * 32)
    blob = old.encrypt_text("legacy", aad.USER_EMAIL)
    rotated = Crypto({"k1": bytes(range(32)), "k0": bytes(range(1, 33))}, "k1", b"b" * 32, b"p" * 32)
    assert rotated.decrypt_text(blob, aad.USER_EMAIL) == "legacy"


def test_file_envelope(crypto):
    blob, wrapped = crypto.encrypt_file(b"\x00pdf-bytes", "kyc|1")
    assert crypto.decrypt_file(blob, wrapped, "kyc|1") == b"\x00pdf-bytes"
    with pytest.raises(CryptoError):
        crypto.decrypt_file(blob, wrapped, "kyc|2")


def test_blind_index_is_deterministic_and_purpose_separated(crypto):
    assert crypto.blind_index("email", "a@b.c") == crypto.blind_index("email", "a@b.c")
    assert crypto.blind_index("email", "a@b.c") != crypto.blind_index("phone", "a@b.c")


def test_short_keys_rejected():
    with pytest.raises(CryptoError):
        Crypto({"k": b"short"}, "k", b"b" * 32, b"p" * 32)
    with pytest.raises(CryptoError):
        Crypto({"k": bytes(32)}, "k", b"b" * 8, b"p" * 32)


def test_sign_is_purpose_separated(crypto):
    assert crypto.sign("a", b"x") == crypto.sign("a", b"x")
    assert crypto.sign("a", b"x") != crypto.sign("b", b"x")
