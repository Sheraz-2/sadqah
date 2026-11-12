"""Bodies for the recipient KYC steps. Mirrors docs/API_CONTRACT.md. Documents arrive as multipart, not JSON."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocType = Literal["national_id", "passport", "utility_bill", "selfie", "bank_statement", "proof_of_income"]


class IdentityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    date_of_birth: date
    id_number: str = Field(min_length=5, max_length=40)
    address: str = Field(min_length=5, max_length=300)
    doc_country: str = Field(pattern=r"^[A-Za-z]{2}$")
    consent_biometric: Literal[True]
    consent_data: Literal[True]

    @field_validator("date_of_birth")
    @classmethod
    def _adult(cls, v: date) -> date:
        today = date.today()
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if not 18 <= age <= 110:
            raise ValueError("You must be at least 18 years old to apply.")
        return v


class LivenessOut(BaseModel):
    challenge_token: str
    code: str
    expires_at: str


class DocumentStoredOut(BaseModel):
    doc_type: DocType
    uploaded_at: str


class SubmitOut(BaseModel):
    status: str
    missing: list[str]
