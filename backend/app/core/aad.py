"""Associated-data labels for field encryption (see Crypto.encrypt).

A ciphertext only decrypts under the label it was written with, so a value copied from one column (or one
donation's message thread) into another fails authentication instead of decrypting.
"""
from __future__ import annotations

import re
import uuid

USER_EMAIL = "users.email_enc"
USER_PHONE = "users.phone_enc"
RECEIVER = "recipients.paypal_receiver_enc"
KYC_FULL_NAME = "recipients_kyc.full_name_enc"
KYC_DOB = "recipients_kyc.dob_enc"
KYC_NIC = "recipients_kyc.nic_number_enc"
KYC_ADDRESS = "recipients_kyc.address_enc"
PAYER_REF = "donation_payer_private.payer_ref_enc"


def message(donation_id: object) -> str:
    """Message bodies are bound to their donation thread."""
    return f"anonymous_messages.body_enc|{donation_id}"


# ---- support requests ----------------------------------------------------------------------------------------------
# Four encrypted fields per support request. The field name is part of the associated data, so a ciphertext cannot be moved from one
# field to another, and the request UUID is part of it too, so it cannot be moved to another request (or into the donation-message
# domain above). The allow-list is explicit: a new field must be added here on purpose, never derived from caller input.
SUPPORT_FIELDS = ("body", "reply_email", "response", "internal_note")

_CANONICAL_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def support(field: str, request_id: object) -> str:
    """Associated data for one encrypted field of one support request.

    `request_id` is a `uuid.UUID` or its canonical hyphenated string (any letter case); both give the same lower-case label. Anything
    else (other types, braces/urn/unhyphenated spellings, the nil UUID) raises ValueError, as does a field outside `SUPPORT_FIELDS`.
    """
    if not isinstance(field, str) or field not in SUPPORT_FIELDS:
        raise ValueError("unknown support field")
    if isinstance(request_id, uuid.UUID):
        rid = request_id
    elif isinstance(request_id, str) and _CANONICAL_UUID.fullmatch(request_id):
        rid = uuid.UUID(request_id)
    else:
        raise ValueError("support request id must be a UUID")
    if rid.int == 0:
        raise ValueError("support request id must not be the nil UUID")
    return f"support_requests.{field}_enc|{rid}"
