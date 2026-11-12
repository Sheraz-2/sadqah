"""Shared fixtures. Tests here are pure logic: no database, no network, no PayPal."""
import os
import sys
import types

import pytest

try:  # pragma: no cover - real environments have the package (it is a declared dependency)
    import pydantic_settings  # noqa: F401
except ModuleNotFoundError:  # minimal stand-in so config-importing modules load in a bare sandbox
    from pydantic import BaseModel

    class _BaseSettings(BaseModel):
        def __init__(self, **kw):
            fields = type(self).model_fields
            env = {k: os.environ[k.upper()] for k in fields if k.upper() in os.environ}
            super().__init__(**{**env, **kw})

    shim = types.ModuleType("pydantic_settings")
    shim.BaseSettings = _BaseSettings
    shim.SettingsConfigDict = dict
    sys.modules["pydantic_settings"] = shim

for _name in ("asyncpg", "anthropic", "redis", "httpx"):  # only imported for types/clients by modules under test
    try:
        __import__(_name)
    except ModuleNotFoundError:
        _stub = types.ModuleType(_name)
        _stub.__getattr__ = lambda attr, _n=_name: type(attr, (Exception,), {})  # any attribute is a dummy class
        sys.modules[_name] = _stub

from app.core.crypto import Crypto  # noqa: E402


@pytest.fixture()
def crypto() -> Crypto:
    return Crypto(
        keys={"k1": bytes(range(32)), "k0": bytes(range(1, 33))},
        active_key_id="k1",
        blind_index_key=b"b" * 32,
        token_pepper=b"p" * 32,
    )
