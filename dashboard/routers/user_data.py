"""User-scoped data API - scope picker, export, erasure.

Mirrors TheHost's ``/api/user/*`` surface so the two dashboards behave the same
under one SSO session. What differs is the payload: ImperialReminder has no
per-member tracking to export or opt out of, so the only account-linked records
are admin audit entries (see ``services/user_data.py``; premium was removed
2026-08-24, so no entitlement records exist any more).
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboard.auth.dependencies import get_current_user
from dashboard.services import user_data as user_data_service
from storage.log import get_logger

logger = get_logger("dashboard.routers.user_data")

router = APIRouter(tags=["user-data"])


def _parse_guild_id(guild_id: str | None) -> str | None:
    """Validate an optional guild scope. Empty/absent means 'all servers'."""
    if guild_id is None or guild_id == "":
        return None
    if not guild_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid guild_id")
    return guild_id


async def _resolve_guild_scope(
    session: dict, guild_id: str | None, user_id: str
) -> str | None:
    """Validate the scope: the user must be a member of the server, OR hold
    stored records there. Records can outlive membership (left server, stale
    session) and ``user_guilds(with_data=true)`` deliberately lists those
    guilds in the scope picker - so they must stay actionable here, or the
    picker offers rows that summary/export/erase then refuse. Every query
    downstream filters by the caller's own user id, so a non-member scope can
    only ever reach the caller's own records."""
    gid = _parse_guild_id(guild_id)
    if gid is None:
        return None
    if any(str(g.get("id")) == gid for g in session.get("guilds", [])):
        return gid
    if gid in await user_data_service.guild_ids_with_data(user_id):
        return gid
    raise HTTPException(
        status_code=404,
        detail=(
            "You are not a member of this server and have no stored records "
            "there (or your session is stale)."
        ),
    )


@router.get("/user/guilds")
async def user_guilds(
    with_data: bool = Query(False),
    session: dict = Depends(get_current_user),
):
    """Servers the user belongs to, from the cached session.

    With ``with_data=true``, only servers where the user has stored records are
    returned - the privacy scope picker uses it so users only see servers they
    can actually act on.
    """
    base = [
        {"id": str(g["id"]), "name": g.get("name"), "icon": g.get("icon")}
        for g in session.get("guilds", [])
    ]
    if not with_data:
        return base

    user_id = str(session["user_id"])
    data_ids = await user_data_service.guild_ids_with_data(user_id)
    filtered = [g for g in base if g["id"] in data_ids]

    # Records can outlive membership (left server, stale session) - surface those
    # too, unnamed, so the data is still reachable.
    known_ids = {g["id"] for g in base}
    for gid in data_ids - known_ids:
        filtered.append({"id": gid, "name": None, "icon": None})
    return filtered


@router.get("/user/data/summary")
async def data_summary(
    guild_id: str | None = Query(None),
    session: dict = Depends(get_current_user),
):
    """How many records name this account, in the selected scope.

    The privacy page shows this instead of describing the export in the
    abstract: a user should be able to see that there are (say) four audit
    entries before deciding whether to download or erase them.
    """
    user_id = str(session["user_id"])
    gid = await _resolve_guild_scope(session, guild_id, user_id)
    return await user_data_service.summary(user_id, gid)


@router.get("/user/data/export")
async def export_data(
    guild_id: str | None = Query(None),
    session: dict = Depends(get_current_user),
):
    user_id = str(session["user_id"])
    gid = await _resolve_guild_scope(session, guild_id, user_id)
    payload = await user_data_service.export_all(user_id, gid)
    body = json.dumps(payload, indent=2, default=str).encode("utf-8")

    def _iter():
        yield body

    suffix = f"-guild-{gid}" if gid is not None else ""
    filename = f"imperial-reminder-data-{user_id}{suffix}.json"
    return StreamingResponse(
        _iter(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class DeleteRequest(BaseModel):
    confirm: bool = False
    guild_id: str | None = None


@router.delete("/user/data")
async def delete_data(
    body: DeleteRequest,
    session: dict = Depends(get_current_user),
):
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Delete must be confirmed by sending {confirm: true}.",
        )
    user_id = str(session["user_id"])
    gid = await _resolve_guild_scope(session, body.guild_id, user_id)
    deleted = await user_data_service.erase_all(user_id, gid)
    logger.info(
        "Erased user data for %s (guild=%s): %s", user_id, gid or "all", deleted
    )
    return {
        "user_id": user_id,
        "guild_id": gid,
        "deleted": deleted,
    }
