"""Member-tier API - what this server's bump reminder is doing for YOU.

Everything here is gated on ``require_guild_member``: signed in, and in this
server according to the session's Discord guild list. It is deliberately NOT
``require_panel_access`` - a plain member with no Manage Server and no panel
role reaches these routes, which is the whole point of the member view.

The hard rule for this file: **no manager-only values ever leave it.** No
channel ids, no role ids, no custom message text, no admin role lists. A member
gets booleans and timings ("a bump is due in 40 minutes", "yes you get pinged"),
never the setup itself. Anything added here must pass that test.

Each endpoint stands alone so the dashboard can fetch them additively - the
"will you be pinged" check needs a live Discord member fetch, and it must not
be able to take the bump timings down with it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from dashboard.auth.dependencies import require_guild_member
from dashboard.services import stats as stats_service
from storage.config_manager import get_guild_config_manager
from storage.settings.collections import db_manager
from storage.log import get_logger
from storage.sub_systems.bump_config import BUMP_BOTS

logger = get_logger("dashboard.routers.member")

router = APIRouter(tags=["member"])


@router.get("/guilds/{guild_id}/member/bumps")
async def member_bumps(guild_id: int, _session: dict = Depends(require_guild_member)):
    """Per-bot bump timings for a member of this server.

    The rows come from the same ``stats_service.guild_bump_stats`` the admin
    overview uses, so a member and a manager can never be told two different
    stories about the same cooldown. That payload carries no channel or role
    ids - only bot keys, timings and status - which is why it is safe here.
    """
    gcm = await get_guild_config_manager(db_manager)
    config = await gcm.get_config(guild_id)
    return stats_service.guild_bump_stats(config)


@router.get("/guilds/{guild_id}/member/reminder")
async def member_reminder(guild_id: int, session: dict = Depends(require_guild_member)):
    """Whether this member is one of the people the bump reminder pings.

    ``you_will_be_pinged`` is deliberately three-valued. Saying "you will not be
    pinged" to somebody who actually holds the role is the one wrong answer this
    endpoint could give, and it is the one that would make them miss a bump, so
    "we could not confirm" is ``null`` rather than a confident "no".

    Updated 2026-08-17: the engine can now tell the two apart. ``member_role_ids``
    returned an empty set both for "holds no roles" and for "Discord did not
    answer", so this endpoint treated ANY empty answer as unknown - correct in
    the dangerous direction, but it also refused to answer for a member who
    genuinely holds no roles, which is a question we could always have answered.
    ``member_roles_lookup`` carries ``resolved``, so unknown now means only what
    it says.
    """
    from dashboard._engine.auth.panel_access import member_roles_lookup

    gcm = await get_guild_config_manager(db_manager)
    config = await gcm.get_config(guild_id)

    role_configured = bool(config.bump_role)
    watching = bool(config.bump_channel)
    tracked = len([b for b in (config.enabled_bots or []) if b in BUMP_BOTS])

    if not role_configured:
        return {
            "reminder_role_set": False,
            "bump_channel_set": watching,
            "bots_tracked": tracked,
            "you_will_be_pinged": False,
            "status": "no_role",
        }

    user_id = session.get("user_id") or (session.get("user_data") or {}).get("id")
    if not user_id:
        return {
            "reminder_role_set": True,
            "bump_channel_set": watching,
            "bots_tracked": tracked,
            "you_will_be_pinged": None,
            "status": "unknown",
        }

    try:
        lookup = await member_roles_lookup(str(guild_id), str(user_id))
    except Exception:
        logger.warning(
            "member role lookup failed for %s in guild %s", user_id, guild_id, exc_info=True
        )
        lookup = None

    # Only an unanswered lookup is unknown. A resolved one that came back empty is a
    # real answer: this member holds no roles, so they are not being pinged.
    if lookup is None or not lookup.resolved:
        return {
            "reminder_role_set": True,
            "bump_channel_set": watching,
            "bots_tracked": tracked,
            "you_will_be_pinged": None,
            "status": "unknown",
        }
    held = lookup.roles

    pinged = str(config.bump_role) in held
    return {
        "reminder_role_set": True,
        "bump_channel_set": watching,
        "bots_tracked": tracked,
        "you_will_be_pinged": pinged,
        "status": "yes" if pinged else "no",
    }
