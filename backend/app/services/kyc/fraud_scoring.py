"""Deterministic fraud and consistency scoring for a KYC case.

The vision model reads documents; THIS module decides what is suspicious, using fixed rules and weights that
a reviewer can audit. Output is a 0..1 risk score and a list of flags {code, severity, detail}. It never
approves or rejects anyone: a human does that, and the database refuses approval without one.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any


def _norm(text: str | None) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def name_similarity(a: str | None, b: str | None) -> float:
    """Order-insensitive: 'Khan Bilal' matches 'Bilal Khan'."""
    ta, tb = sorted(_norm(a).split()), sorted(_norm(b).split())
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()


def text_similarity(a: str | None, b: str | None) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    return max(SequenceMatcher(None, na, nb).ratio(), len(ta & tb) / max(1, min(len(ta), len(tb))))


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


@dataclass
class CaseInputs:
    declared_name: str
    declared_dob: str
    declared_id_number: str          # canonical form (see validation.normalize_nic)
    declared_address: str
    id_doc: dict[str, Any] | None = None
    bill: dict[str, Any] | None = None
    income_docs: list[dict[str, Any]] = field(default_factory=list)
    selfie: dict[str, Any] | None = None
    expected_liveness_code: str | None = None
    face_match: float | None = None
    face_min_score: float = 0.85
    duplicate_document_count: int = 0
    infected_document: bool = False
    today: date = field(default_factory=date.today)


def score_case(c: CaseInputs) -> tuple[float, list[dict[str, str]]]:
    flags: list[dict[str, str]] = []
    risk = 0.0

    def flag(code: str, severity: str, detail: str, weight: float) -> None:
        nonlocal risk
        flags.append({"code": code, "severity": severity, "detail": detail})
        risk += weight

    if c.infected_document:
        flag("infected_document", "critical", "An uploaded file failed the malware scan.", 1.0)
    if c.duplicate_document_count:
        flag("duplicate_document", "critical",
             f"{c.duplicate_document_count} uploaded file(s) are byte-identical to documents on another recipient's case.", 0.4)

    # ---- identity document vs what the person declared
    idd = c.id_doc
    if idd is None:
        flag("id_unreadable", "warning", "The identity document could not be read automatically.", 0.15)
    else:
        sim = name_similarity(c.declared_name, idd.get("full_name"))
        if sim < 0.75:
            flag("name_mismatch", "critical", "The name on the identity document does not match the name entered.", 0.30)
        elif sim < 0.9:
            flag("name_close_match", "warning", "The name on the identity document differs slightly from the name entered.", 0.10)
        doc_dob = _parse_date(idd.get("date_of_birth"))
        if doc_dob is None or str(doc_dob) != str(c.declared_dob)[:10]:
            flag("dob_mismatch", "critical", "The date of birth on the identity document does not match the one entered.", 0.25)
        doc_number = re.sub(r"[^A-Za-z0-9]", "", str(idd.get("id_number") or "")).upper()
        if not doc_number or doc_number != c.declared_id_number:
            flag("id_number_mismatch", "critical", "The identity number on the document does not match the one entered.", 0.30)
        expiry = _parse_date(idd.get("expiry_date"))
        if expiry and expiry < c.today:
            flag("id_expired", "warning", f"The identity document expired on {expiry.isoformat()}.", 0.10)
        if idd.get("face_photo_present") is False:
            flag("id_without_photo", "warning", "No portrait was found on the identity document.", 0.10)

    # ---- proof of address
    bill = c.bill
    if bill is None:
        flag("bill_unreadable", "warning", "The utility bill could not be read automatically.", 0.10)
    else:
        if text_similarity(c.declared_address, bill.get("service_address")) < 0.5:
            flag("address_mismatch", "warning", "The address on the utility bill does not match the address entered.", 0.15)
        issued = _parse_date(bill.get("issue_date"))
        if issued is None:
            flag("bill_undated", "info", "The utility bill has no readable date.", 0.03)
        elif (c.today - issued).days > 100:
            flag("bill_old", "warning", "The utility bill is more than about three months old.", 0.10)
        if name_similarity(c.declared_name, bill.get("account_holder_name")) < 0.6:
            flag("bill_other_name", "info", "The utility bill is in a different name (common for shared households).", 0.0)

    # ---- income documents
    for ex in c.income_docs:
        holder = ex.get("account_holder_name")
        if holder and name_similarity(c.declared_name, holder) < 0.6:
            flag("income_doc_other_name", "warning", "An income document is in a different name from the applicant.", 0.15)
            break

    # ---- tampering signals reported by the reader (text only; never trusted blindly)
    tamper = [s for ex in [c.id_doc, c.bill, *c.income_docs] if ex for s in ex.get("tamper_signals", [])]
    if tamper:
        flag("tamper_signals", "critical", "Possible tampering noticed: " + "; ".join(tamper[:3]), min(0.25 * len(tamper), 0.5))

    # ---- low legibility / confidence
    for ex in [c.id_doc, c.bill, *c.income_docs]:
        if ex and (ex.get("legible") is False or float(ex.get("confidence", 1)) < 0.5):
            flag("low_confidence_reading", "warning", "At least one document was hard to read; the automatic reading may be wrong.", 0.05)
            break

    # ---- selfie, liveness and face match
    if c.selfie is None:
        flag("selfie_unreadable", "warning", "The selfie could not be analysed.", 0.10)
    else:
        if c.selfie.get("face_visible") is False or c.selfie.get("single_person") is False:
            flag("selfie_not_single_face", "critical", "The selfie does not clearly show exactly one face.", 0.25)
        if c.selfie.get("appears_to_be_screen_or_printed_photo") is True:
            flag("selfie_not_live", "critical", "The selfie looks like a photo of a screen or a printed picture.", 0.25)
        if c.expected_liveness_code and str(c.selfie.get("visible_code") or "") != c.expected_liveness_code:
            flag("liveness_code_mismatch", "critical", "The one-time code was not visible in the selfie.", 0.30)
    if c.face_match is None:
        flag("face_match_unavailable", "warning", "Automatic face comparison was not available; compare the photos by eye.", 0.10)
    elif c.face_match < c.face_min_score:
        flag("face_mismatch", "critical", f"Face similarity {c.face_match:.2f} is below the {c.face_min_score:.2f} threshold.", 0.35)

    return round(min(1.0, risk), 3), flags
