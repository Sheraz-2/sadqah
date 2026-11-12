"""Phase 5.1: domain-separated, request-bound associated data (AAD) for the four encrypted support-request fields.

Pure logic plus real AES-GCM through the shared `crypto` fixture; no database, route or mailer is involved.
"""
import itertools
import uuid

import pytest

from app.core import aad
from app.core.crypto import CryptoError

FIELDS = ("body", "reply_email", "response", "internal_note")
RID = uuid.UUID("12345678-1234-5678-1234-567812345678")
OTHER_RID = uuid.UUID("87654321-4321-8765-4321-876543218765")


class _DbUuid(uuid.UUID):
    """Database drivers return UUID subclasses (asyncpg does); they must behave exactly like uuid.UUID."""


def test_the_allow_list_is_exactly_the_four_fields_and_cannot_be_mutated():
    assert aad.SUPPORT_FIELDS == FIELDS
    assert isinstance(aad.SUPPORT_FIELDS, tuple)


def test_all_four_fields_give_distinct_contexts_for_the_same_request():
    contexts = [aad.support(f, RID) for f in FIELDS]
    assert len(set(contexts)) == 4
    assert contexts == [f"support_requests.{f}_enc|{RID}" for f in FIELDS]


def test_support_contexts_never_collide_with_any_existing_context():
    existing = {aad.USER_EMAIL, aad.USER_PHONE, aad.RECEIVER, aad.KYC_FULL_NAME, aad.KYC_DOB, aad.KYC_NIC, aad.KYC_ADDRESS, aad.PAYER_REF,
                aad.message(RID)}
    assert not existing & {aad.support(f, RID) for f in FIELDS}


@pytest.mark.parametrize("field", FIELDS)
def test_the_same_field_on_different_requests_gives_different_contexts(field):
    assert aad.support(field, RID) != aad.support(field, OTHER_RID)


@pytest.mark.parametrize("field", FIELDS)
def test_uuid_objects_strings_and_driver_subclasses_give_one_consistent_context(field):
    expected = f"support_requests.{field}_enc|12345678-1234-5678-1234-567812345678"
    assert aad.support(field, RID) == expected
    assert aad.support(field, str(RID)) == expected
    assert aad.support(field, str(RID).upper()) == expected                      # letter case never changes the context
    assert aad.support(field, "12345678-1234-5678-1234-567812345678".swapcase()) == expected
    assert aad.support(field, _DbUuid(str(RID))) == expected
    assert aad.support(field, uuid.UUID(int=RID.int)) == expected


@pytest.mark.parametrize("field", ["", " ", "sender_email", "email", "reply", "Body", "BODY", "body ", " body", "body\n", "body_enc",
                                   "support_requests.body_enc", "body|x", "internal-note", "internal_note\x00", None, 1, b"body",
                                   ("body",), ["body"], object()])
def test_unknown_or_malformed_fields_are_rejected(field):
    with pytest.raises(ValueError, match="unknown support field"):
        aad.support(field, RID)


@pytest.mark.parametrize("bad", ["not-a-uuid", "", " ", None, 0, 1, 12345678123456781234567812345678, b"1234567812345678", [], object(),
                                 "12345678-1234-5678-1234-56781234567",              # too short
                                 "12345678-1234-5678-1234-5678123456789",            # too long
                                 "12345678123456781234567812345678",                 # unhyphenated
                                 "{12345678-1234-5678-1234-567812345678}",           # braces
                                 "urn:uuid:12345678-1234-5678-1234-567812345678",    # urn form
                                 " 12345678-1234-5678-1234-567812345678",            # leading space
                                 "12345678-1234-5678-1234-567812345678 ",            # trailing space
                                 "12345678-1234-5678-1234-567812345678\n",           # trailing newline
                                 "1234567g-1234-5678-1234-567812345678",             # non-hex
                                 "12345678-1234-5678-1234-567812345678|body"])
def test_invalid_request_ids_are_rejected_for_every_field(bad):
    for field in FIELDS:
        with pytest.raises(ValueError):
            aad.support(field, bad)


def test_the_nil_uuid_is_rejected_in_every_spelling():
    for nil in (uuid.UUID(int=0), "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(ValueError, match="nil"):
            aad.support("body", nil)


def test_a_field_error_wins_over_an_id_error_and_errors_do_not_echo_the_input():
    with pytest.raises(ValueError, match="unknown support field"):
        aad.support("nope", "not-a-uuid")
    with pytest.raises(ValueError) as exc:
        aad.support("body", "secret-looking-value")
    assert "secret-looking-value" not in str(exc.value)


@pytest.mark.parametrize("field", FIELDS)
def test_each_field_round_trips_in_its_own_context(crypto, field):
    context = aad.support(field, RID)
    blob = crypto.encrypt_text(f"private {field} value", context)
    assert crypto.decrypt_text(blob, context) == f"private {field} value"
    # spelled differently, still the same context
    assert crypto.decrypt_text(blob, aad.support(field, str(RID).upper())) == f"private {field} value"


@pytest.mark.parametrize(("written", "read"), list(itertools.permutations(FIELDS, 2)))
def test_ciphertext_cannot_be_read_under_another_field(crypto, written, read):
    blob = crypto.encrypt_text("private", aad.support(written, RID))
    with pytest.raises(CryptoError):
        crypto.decrypt_text(blob, aad.support(read, RID))


@pytest.mark.parametrize("field", FIELDS)
def test_ciphertext_cannot_be_read_under_another_request(crypto, field):
    blob = crypto.encrypt_text("private", aad.support(field, RID))
    with pytest.raises(CryptoError):
        crypto.decrypt_text(blob, aad.support(field, OTHER_RID))


@pytest.mark.parametrize("field", FIELDS)
def test_support_and_donation_message_ciphertexts_are_not_interchangeable(crypto, field):
    support_blob = crypto.encrypt_text("private", aad.support(field, RID))
    message_blob = crypto.encrypt_text("private", aad.message(RID))                # same UUID value, different domain
    with pytest.raises(CryptoError):
        crypto.decrypt_text(support_blob, aad.message(RID))
    with pytest.raises(CryptoError):
        crypto.decrypt_text(message_blob, aad.support(field, RID))


def test_ciphertext_cannot_be_read_under_an_unrelated_existing_context(crypto):
    blob = crypto.encrypt_text("private", aad.support("reply_email", RID))
    for other in (aad.USER_EMAIL, aad.USER_PHONE, aad.PAYER_REF, aad.RECEIVER):
        with pytest.raises(CryptoError):
            crypto.decrypt_text(blob, other)


def test_existing_aad_labels_and_message_context_are_unchanged():
    assert aad.USER_EMAIL == "users.email_enc"
    assert aad.USER_PHONE == "users.phone_enc"
    assert aad.RECEIVER == "recipients.paypal_receiver_enc"
    assert aad.KYC_FULL_NAME == "recipients_kyc.full_name_enc"
    assert aad.KYC_DOB == "recipients_kyc.dob_enc"
    assert aad.KYC_NIC == "recipients_kyc.nic_number_enc"
    assert aad.KYC_ADDRESS == "recipients_kyc.address_enc"
    assert aad.PAYER_REF == "donation_payer_private.payer_ref_enc"
    assert aad.message(RID) == "anonymous_messages.body_enc|12345678-1234-5678-1234-567812345678"
    assert aad.message("any-object") == "anonymous_messages.body_enc|any-object"        # message() is still not validating, as before
    assert aad.message(RID).startswith("anonymous_messages.body_enc|")
