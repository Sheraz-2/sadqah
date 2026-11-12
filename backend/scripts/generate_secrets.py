#!/usr/bin/env python3
"""Prints fresh secrets for a SadQah deployment, ready to paste into your .env / secret manager. Standard library only.

    python backend/scripts/generate_secrets.py            # plain KEY=value lines
    python backend/scripts/generate_secrets.py --key-id v2  # name the encryption key (use when rotating)

Rotation: keep the old key in ENCRYPTION_KEYS (comma separated, "id:base64"), add the new one, set ACTIVE_KEY_ID to the new id.
Never reuse these values across environments, never commit them, and back them up: losing ENCRYPTION_KEYS makes every
encrypted field and KYC document unreadable, and changing BLIND_INDEX_KEY or TOKEN_PEPPER breaks e-mail lookups and tracking tokens.
"""
from __future__ import annotations

import argparse
import base64
import secrets


def b64(n: int = 32) -> str:
    return base64.b64encode(secrets.token_bytes(n)).decode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key-id", default="v1", help="id for the new encryption key (default: v1)")
    args = parser.parse_args()
    if not args.key_id.replace("_", "").replace("-", "").isalnum() or not 1 <= len(args.key_id) <= 32:
        parser.error("--key-id must be 1-32 letters, digits, - or _")
    print(f"ENCRYPTION_KEYS={args.key_id}:{b64()}")
    print(f"ACTIVE_KEY_ID={args.key_id}")
    print(f"BLIND_INDEX_KEY={b64()}")
    print(f"TOKEN_PEPPER={b64()}")
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}")


if __name__ == "__main__":
    main()
