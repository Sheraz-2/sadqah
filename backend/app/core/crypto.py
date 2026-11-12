"""Application-level encryption, blind indexes and token hashing.

Why application-level: the database (and anyone who steals a backup or a replica) only ever holds
ciphertext for names, ID numbers, addresses, phone numbers, payout destinations and message bodies.

Layout of an encrypted field:  [version=1][len(key_id)][key_id][nonce 12][AES-256-GCM ciphertext+tag]
  * key_id lets us rotate: encrypt with the active key, still decrypt with older ones.
  * AAD (associated data) binds a ciphertext to its column, so a value copied into another column
    or another row's context fails authentication instead of decrypting.

Files use envelope encryption: a fresh 256-bit data key per file, wrapped by the master key.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

_FIELD_VERSION = 1
_FILE_MAGIC = b"SQF1"


class CryptoError(Exception):
    """Raised when data cannot be decrypted or authenticated. Never include plaintext in the message."""


class Crypto:
    def __init__(self, keys: dict[str, bytes], active_key_id: str, blind_index_key: bytes, token_pepper: bytes) -> None:
        if active_key_id not in keys:
            raise CryptoError("active encryption key id is not among the configured keys")
        for kid, key in keys.items():
            if len(key) != 32:
                raise CryptoError(f"encryption key {kid!r} must be 32 bytes")
            if not 1 <= len(kid.encode()) <= 32:
                raise CryptoError("key ids must be 1 to 32 bytes")
        if len(blind_index_key) < 32 or len(token_pepper) < 32:
            raise CryptoError("blind index key and token pepper must be at least 32 bytes")
        self._keys = keys
        self._active = active_key_id
        self._blind = blind_index_key
        self._pepper = token_pepper
        self._subkeys: dict[tuple[str, bytes], bytes] = {}

    # ------------------------------------------------------------------ key handling
    def _subkey(self, key_id: str, purpose: bytes) -> bytes:
        cache_key = (key_id, purpose)
        sub = self._subkeys.get(cache_key)
        if sub is None:
            sub = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"sadqah/" + purpose).derive(self._keys[key_id])
            self._subkeys[cache_key] = sub
        return sub

    # ------------------------------------------------------------------ fields
    def encrypt(self, plaintext: bytes, aad: str, purpose: bytes = b"field/v1") -> bytes:
        kid = self._active.encode()
        nonce = os.urandom(12)
        ct = AESGCM(self._subkey(self._active, purpose)).encrypt(nonce, plaintext, aad.encode())
        return bytes([_FIELD_VERSION, len(kid)]) + kid + nonce + ct

    def decrypt(self, blob: bytes, aad: str, purpose: bytes = b"field/v1") -> bytes:
        try:
            blob = bytes(blob)
            if len(blob) < 2 + 1 + 12 + 16 or blob[0] != _FIELD_VERSION:
                raise CryptoError("unrecognised ciphertext")
            klen = blob[1]
            kid = blob[2 : 2 + klen].decode()
            if kid not in self._keys:
                raise CryptoError("ciphertext was written with an unknown key id")
            nonce = blob[2 + klen : 2 + klen + 12]
            ct = blob[2 + klen + 12 :]
            return AESGCM(self._subkey(kid, purpose)).decrypt(nonce, ct, aad.encode())
        except InvalidTag as exc:
            raise CryptoError("ciphertext failed authentication") from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise CryptoError("malformed ciphertext") from exc

    def encrypt_text(self, text: str, aad: str) -> bytes:
        return self.encrypt(text.encode("utf-8"), aad)

    def decrypt_text(self, blob: bytes, aad: str) -> str:
        return self.decrypt(blob, aad).decode("utf-8")

    # ------------------------------------------------------------------ files (envelope)
    def encrypt_file(self, data: bytes, aad: str) -> tuple[bytes, bytes]:
        """Returns (encrypted blob for object storage, wrapped data key for the database)."""
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        blob = _FILE_MAGIC + nonce + AESGCM(dek).encrypt(nonce, data, aad.encode())
        wrapped = self.encrypt(dek, aad="dek|" + aad, purpose=b"wrap/v1")
        return blob, wrapped

    def decrypt_file(self, blob: bytes, wrapped_dek: bytes, aad: str) -> bytes:
        if not blob.startswith(_FILE_MAGIC) or len(blob) < 4 + 12 + 16:
            raise CryptoError("unrecognised file container")
        dek = self.decrypt(wrapped_dek, aad="dek|" + aad, purpose=b"wrap/v1")
        nonce = blob[4:16]
        try:
            return AESGCM(dek).decrypt(nonce, blob[16:], aad.encode())
        except InvalidTag as exc:
            raise CryptoError("file failed authentication") from exc

    # ------------------------------------------------------------------ blind indexes & tokens
    def blind_index(self, purpose: str, value: str) -> bytes:
        """Deterministic keyed hash for equality lookups and uniqueness without storing plaintext."""
        return hmac.new(self._blind, purpose.encode() + b"\x00" + value.encode("utf-8"), hashlib.sha256).digest()

    def hash_token(self, normalised_token_payload: str) -> bytes:
        """Peppered hash of a Donation Token. Only this hash is ever stored."""
        return hmac.new(self._pepper, b"donation-token\x00" + normalised_token_payload.encode(), hashlib.sha256).digest()

    def keyed_hash(self, purpose: str, value: bytes) -> bytes:
        """General purpose keyed hash (rate-limit keys, pseudonymous ids) that never exposes raw values."""
        return hmac.new(self._pepper, purpose.encode() + b"\x00" + value, hashlib.sha256).digest()

    def sign(self, purpose: str, payload: bytes) -> bytes:
        """HMAC used for short-lived stateless challenges (e.g. selfie liveness codes)."""
        return hmac.new(self._subkey(self._active, b"sign/v1"), purpose.encode() + b"\x00" + payload, hashlib.sha256).digest()


@lru_cache
def get_crypto() -> Crypto:
    s = get_settings()
    import base64

    return Crypto(
        keys=s.parsed_encryption_keys(),
        active_key_id=s.active_key_id,
        blind_index_key=base64.b64decode(s.blind_index_key or ""),
        token_pepper=base64.b64decode(s.token_pepper or ""),
    )
