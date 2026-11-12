"""What an application still needs before it can be submitted. Mirrors api.fn_kyc_submit (the database is the authority;
this only lets the portal show a checklist before the applicant presses submit). Pure function."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def missing_requirements(identity_saved: bool, documents: Iterable[Mapping[str, Any]]) -> list[str]:
    usable = {d["doc_type"] for d in documents if d.get("scan_status") != "infected"}
    missing: list[str] = []
    if not identity_saved:
        missing.append("identity_details_and_consent")
    if not usable & {"national_id", "passport"}:
        missing.append("national_id_or_passport")
    if "utility_bill" not in usable:
        missing.append("utility_bill")
    if "selfie" not in usable:
        missing.append("selfie")
    if not usable & {"bank_statement", "proof_of_income"}:
        missing.append("bank_statement_or_proof_of_income")
    return missing
