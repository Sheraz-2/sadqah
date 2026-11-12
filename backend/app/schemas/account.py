"""Request and response bodies for account settings (password change, deletion, data export)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChangePasswordRequest(_Request):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class DeleteAccountRequest(_Request):
    password: str = Field(min_length=1, max_length=128)
    confirm: Literal["DELETE"]  # the person must type the word, so a stray click cannot delete an account


class AccountSettingsOut(BaseModel):
    role: str
    email: str
    phone: str | None
    display_name: str | None
    country_code: str | None
    show_on_leaderboard: bool
    can_delete: bool
    delete_blockers: list[str]


class DeletedOut(BaseModel):
    deleted: bool = True
    files_erased: int
