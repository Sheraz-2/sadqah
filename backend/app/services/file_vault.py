"""Where uploaded files live.

  vault   private. KYC documents. Every object is envelope-encrypted (fresh AES-256-GCM data key per
          file, wrapped by the master key held in env/KMS). Object keys are random and say nothing.
          Reviewers read decrypted bytes only through the audited admin endpoint, never via a public URL.
  public  campaign update photos. Re-encoded images with random keys, served by GET /media/{key}.

Backends: local directory (default; mount encrypted storage in production) or any S3-compatible bucket.
"""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import struct
from pathlib import Path

from app.core.config import Settings
from app.core.crypto import Crypto

_KEY_RE = re.compile(r"^[a-f0-9]{32}(\.[a-z0-9]{1,5})?$")


def new_object_key(extension: str = "") -> str:
    key = secrets.token_hex(16)
    return f"{key}.{extension}" if extension else key


def valid_key(key: str) -> bool:
    return bool(_KEY_RE.match(key))


class FileVault:
    def __init__(self, settings: Settings, crypto: Crypto) -> None:
        self._s = settings
        self._crypto = crypto
        self._vault = Path(settings.vault_dir)
        self._public = Path(settings.public_media_dir)
        self._s3 = None
        if settings.storage_backend == "s3":
            import boto3  # optional dependency: pip install .[s3]

            self._s3 = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.s3_region)

    # ------------------------------------------------------------------ raw byte storage
    def _path(self, root: Path, key: str) -> Path:
        if not valid_key(key):
            raise ValueError("invalid object key")
        return root / key[:2] / key

    async def _write(self, area: str, key: str, data: bytes) -> None:
        if self._s3 is not None:
            await asyncio.to_thread(self._s3.put_object, Bucket=self._s.s3_bucket, Key=f"{area}/{key}", Body=data,
                                    ServerSideEncryption="AES256")
            return
        root = self._vault if area == "vault" else self._public

        def write() -> None:
            path = self._path(root, key)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = path.with_suffix(path.suffix + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)

        await asyncio.to_thread(write)

    async def _read(self, area: str, key: str) -> bytes:
        if self._s3 is not None:
            def fetch() -> bytes:
                return self._s3.get_object(Bucket=self._s.s3_bucket, Key=f"{area}/{key}")["Body"].read()

            return await asyncio.to_thread(fetch)
        root = self._vault if area == "vault" else self._public
        return await asyncio.to_thread(self._path(root, key).read_bytes)

    async def _delete(self, area: str, key: str) -> None:
        if self._s3 is not None:
            await asyncio.to_thread(self._s3.delete_object, Bucket=self._s.s3_bucket, Key=f"{area}/{key}")
            return
        root = self._vault if area == "vault" else self._public

        def remove() -> None:
            self._path(root, key).unlink(missing_ok=True)

        await asyncio.to_thread(remove)

    async def erase(self, refs: list[str]) -> int:
        """Deletes files named like 'vault:<key>' or 'public:<key>' (what api.fn_delete_my_account returns).
        Best effort: a file that is already gone or cannot be removed is skipped, and the count of erased files is returned."""
        done = 0
        for ref in refs:
            area, _, key = ref.partition(":")
            if area not in ("vault", "public") or not valid_key(key):
                continue
            try:
                await self._delete(area, key)
                if area == "vault":
                    await self._delete("vault", self._sidecar_key(key))
                done += 1
            except (OSError, ValueError, KeyError):
                continue
        return done

    # ------------------------------------------------------------------ private vault
    async def put_private(self, object_key: str, data: bytes) -> bytes:
        """Encrypts and stores. Returns the wrapped data key, which belongs in kyc_documents.wrapped_dek."""
        blob, wrapped = self._crypto.encrypt_file(data, aad=f"kyc|{object_key}")
        await self._write("vault", object_key, blob)
        return wrapped

    async def get_private(self, object_key: str, wrapped_dek: bytes) -> bytes:
        blob = await self._read("vault", object_key)
        return self._crypto.decrypt_file(blob, bytes(wrapped_dek), aad=f"kyc|{object_key}")

    async def put_private_sidecar(self, object_key: str, data: bytes) -> None:
        """Small encrypted companion object whose data key travels inside the file (no database column needed)."""
        blob, wrapped = self._crypto.encrypt_file(data, aad=f"kycmeta|{object_key}")
        await self._write("vault", self._sidecar_key(object_key), struct.pack(">H", len(wrapped)) + wrapped + blob)

    async def get_private_sidecar(self, object_key: str) -> bytes | None:
        try:
            raw = await self._read("vault", self._sidecar_key(object_key))
        except (FileNotFoundError, KeyError, OSError):
            return None
        (n,) = struct.unpack(">H", raw[:2])
        return self._crypto.decrypt_file(raw[2 + n :], raw[2 : 2 + n], aad=f"kycmeta|{object_key}")

    @staticmethod
    def _sidecar_key(object_key: str) -> str:
        return object_key[:32] + ".m"      # still matches the strict key pattern

    # ------------------------------------------------------------------ public media
    async def put_public(self, key: str, data: bytes) -> None:
        await self._write("public", key, data)

    async def public_path(self, key: str) -> Path | None:
        if self._s3 is not None or not valid_key(key):
            return None
        path = self._path(self._public, key)
        return path if await asyncio.to_thread(path.is_file) else None

    async def get_public(self, key: str) -> bytes | None:
        if not valid_key(key):
            return None
        try:
            return await self._read("public", key)
        except (FileNotFoundError, KeyError, OSError):
            return None
