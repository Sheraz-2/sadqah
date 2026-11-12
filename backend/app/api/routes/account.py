"""Account settings. Any signed-in person.

    GET  /account/settings   what the settings page shows, including whether the account can be deleted right now
    POST /account/password   change password (needs the current one)
    GET  /account/export     download everything SadQah holds about you, as JSON
    POST /account/delete     permanently erase the account (needs the password and the word DELETE)

Deleting is a *tombstone*, not a SQL DELETE: gifts, ledger rows and the audit log must stay consistent, so the person's
name, e-mail, phone, identity data and files are erased and what is left is an inactive shell (database/patches/001).
Staff accounts cannot be deleted here. A recipient with money still on its way cannot delete until it has settled.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.deps import AppState, limit_by_key, rate_limit, require_session, state
from app.api.routes.auth import _load_me, _stale_session
from app.core import errors
from app.core.security import Session, clear_session_cookies, hash_password, password_problem, verify_password
from app.schemas.account import AccountSettingsOut, ChangePasswordRequest, DeleteAccountRequest, DeletedOut

router = APIRouter(prefix="/account", tags=["account"])
log = logging.getLogger("sadqah.account")

_LIMIT = rate_limit("account", 60, 600)

_GET_HASH = "SELECT api.fn_get_my_password_hash()"
_SET_HASH = "SELECT api.fn_set_my_password_hash($1)"
_BLOCKERS = "SELECT api.fn_delete_blockers()"
_DELETE = "SELECT api.fn_delete_my_account()"
_LEADERBOARD = "SELECT show_publicly FROM api.my_leaderboard_pref"
_MY_DONATIONS = "SELECT id, campaign_slug, campaign_title, amount_cents, status, created_at, paid_out_at FROM api.my_donations ORDER BY created_at DESC"
_MY_PLEDGE = "SELECT kind, percent, amount_cents, frequency, default_anonymous, created_at FROM api.my_pledge"
_MY_GRATITUDE = "SELECT recipient_name, body, created_at FROM api.my_gratitude ORDER BY created_at DESC"
_MY_PROFILE = ("SELECT slug, public_name, story, business_type, region_country, region_admin1, profile_public, kyc_status "
               "FROM api.my_recipient_profile")


async def _check_password(st: AppState, session: Session, password: str) -> None:
    """Re-asks for the password before anything sensitive. Rate limited per account so it cannot be guessed."""
    await limit_by_key(st, "account-password", str(session.user_id), 8, 900)
    async with st.db.api(session.user_id) as conn:
        stored = await conn.fetchval(_GET_HASH)
    ok = await asyncio.to_thread(verify_password, stored or "!", password)
    if not stored or not ok:
        raise errors.ApiError(403, "forbidden", "That password is not correct.", {"password": "That password is not correct."})


@router.get("/settings", response_model=AccountSettingsOut, dependencies=[Depends(_LIMIT)])
async def settings(session: Session = Depends(require_session), st: AppState = Depends(state)) -> Any:
    me = await _load_me(st, session.user_id)
    if me is None or me.role != session.role:
        return _stale_session()
    async with st.db.api(session.user_id) as conn:
        blockers = list(await conn.fetchval(_BLOCKERS) or [])
    return AccountSettingsOut(role=me.role, email=me.email, phone=me.phone, display_name=me.display_name,
                              country_code=me.country_code, show_on_leaderboard=me.show_on_leaderboard,
                              can_delete=not blockers, delete_blockers=blockers)


@router.post("/password", status_code=204, response_class=Response, dependencies=[Depends(_LIMIT)])
async def change_password(body: ChangePasswordRequest, session: Session = Depends(require_session),
                          st: AppState = Depends(state)) -> Response:
    me = await _load_me(st, session.user_id)
    if me is None:
        raise errors.unauthenticated()
    problem = password_problem(body.new_password, me.email)
    if problem:
        raise errors.validation("Please check the highlighted fields.", {"new_password": problem})
    if body.new_password == body.current_password:
        raise errors.validation("Please check the highlighted fields.", {"new_password": "Choose a password you have not used here."})
    await _check_password(st, session, body.current_password)
    new_hash = await asyncio.to_thread(hash_password, body.new_password)
    async with st.db.api(session.user_id) as conn:
        await conn.execute(_SET_HASH, new_hash)
    return Response(status_code=204)


@router.get("/export", dependencies=[Depends(_LIMIT)])
async def export_data(session: Session = Depends(require_session), st: AppState = Depends(state)) -> Any:
    await limit_by_key(st, "account-export", str(session.user_id), 5, 3600)
    me = await _load_me(st, session.user_id)
    if me is None or me.role != session.role:
        return _stale_session()
    async with st.db.api(session.user_id) as conn:
        donations = await conn.fetch(_MY_DONATIONS)
        pledge = await conn.fetch(_MY_PLEDGE)
        gratitude = await conn.fetch(_MY_GRATITUDE)
        profile = await conn.fetchrow(_MY_PROFILE) if me.role == "recipient" else None
    payload = {
        "about_this_file": "Everything SadQah holds that is linked to your account. Anonymous gifts are not linked to any account, so they are not listed.",
        "account": me.model_dump(),
        "public_gifts": [dict(r) for r in donations],
        "giving_plan": [dict(r) for r in pledge],
        "thank_you_notes_received": [dict(r) for r in gratitude],
        "recipient_profile": dict(profile) if profile else None,
    }
    return JSONResponse(jsonable_encoder(payload), headers={
        "Content-Disposition": 'attachment; filename="sadqah-my-data.json"', "Cache-Control": "no-store"})


@router.post("/delete", response_model=DeletedOut, dependencies=[Depends(_LIMIT)])
async def delete_account(body: DeleteAccountRequest, response: Response, session: Session = Depends(require_session),
                         st: AppState = Depends(state)) -> Any:
    await _check_password(st, session, body.password)
    async with st.db.api(session.user_id) as conn:  # a recipient with money in flight gets a 409 with the reason
        refs = list(await conn.fetchval(_DELETE) or [])
    erased = await st.vault.erase(refs)
    if erased < len(refs):
        log.warning("some files of a deleted account could not be erased (%d of %d)", len(refs) - erased, len(refs))
    out = JSONResponse(DeletedOut(files_erased=erased).model_dump())
    clear_session_cookies(out)
    return out
