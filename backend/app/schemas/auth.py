"""Request and response bodies for the auth and account endpoints (docs/API_CONTRACT.md, "Auth and account").

Requests forbid unknown fields. E-mail and phone are only shape-checked here (length); the real
normalisation and validation lives in `app.core.validation` and runs in the route so that the error
messages stay the human-readable ones from that module.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Matches users_display_name_len in database/schema.sql (2 to 40 characters).
DISPLAY_NAME_MIN = 2
DISPLAY_NAME_MAX = 40

Role = Literal["donor", "recipient", "reviewer", "admin"]
SelfServiceRole = Literal["donor", "recipient"]  # the only roles a person may register as


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(_Request):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)  # the 12-character minimum is enforced by security.password_problem
    role: SelfServiceRole
    display_name: str | None = Field(default=None, max_length=200)  # trimmed and length-checked in the route
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    phone: str | None = Field(default=None, max_length=40)


class LoginRequest(_Request):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UpdateMeRequest(_Request):
    """Only the fields that are present are changed; an explicit null or empty display_name clears it."""

    display_name: str | None = Field(default=None, max_length=200)
    show_on_leaderboard: bool | None = None


class MeOut(BaseModel):
    id: str
    role: Role
    email: str
    phone: str | None
    display_name: str | None
    country_code: str | None
    show_on_leaderboard: bool


class UserEnvelope(BaseModel):
    user: MeOut
