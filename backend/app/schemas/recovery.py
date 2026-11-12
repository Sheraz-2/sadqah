"""Bodies for password recovery (self-service and admin-initiated)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResetRequestIn(_Request):
    email: str = Field(min_length=1, max_length=254)
    channel: Literal["email", "sms"] = "email"


class ResetConfirmIn(_Request):
    email: str = Field(min_length=1, max_length=254)
    code: str = Field(min_length=1, max_length=32)
    new_password: str = Field(min_length=1, max_length=128)  # strength is enforced by security.password_problem


class RecoveryOptionsOut(BaseModel):
    email: bool
    sms: bool


class RecoveryAcceptedOut(BaseModel):
    message: str


class AdminResetIn(_Request):
    email: str = Field(min_length=1, max_length=254)


class AdminResetOut(BaseModel):
    status: Literal["code_sent", "no_eligible_account", "too_soon"]
    message: str
