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

import time

from fastapi import APIRouter, Depends

from dashboard.auth.dependencies import require_guild_member
from dashboard.services import stats as stats_service
from storage.config_manager import GuildConfig, get_guild_config_manager
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


async def _holds_bump_role(
    config: GuildConfig, session: dict, guild_id: int
) -> bool | None:
    """Does this member hold the guild's configured bump role?

    Three-valued on purpose, and the middle value is the point: ``None`` means
    the question was not answered, and the page renders it as "we could not
    check". Collapsing that into ``False`` would tell somebody who does help
    bump the server that the dashboard has nothing for them, off nothing more
    than a Discord hiccup - the one wrong answer this function could give.

    A guild with no bump role configured is a real ``False``: there is no role
    to hold, so nothing was left unchecked.
    """
    from dashboard._engine.auth.panel_access import member_roles_lookup

    if not config.bump_role:
        return False

    user_id = session.get("user_id") or (session.get("user_data") or {}).get("id")
    if not user_id:
        return None

    try:
        lookup = await member_roles_lookup(str(guild_id), str(user_id))
    except Exception:
        logger.warning(
            "member role lookup failed for %s in guild %s", user_id, guild_id, exc_info=True
        )
        return None

    # An unresolved lookup is silence from Discord, not a member holding nothing.
    if not lookup.resolved:
        return None
    return str(config.bump_role) in lookup.roles


@router.get("/guilds/{guild_id}/my-bump-view")
async def my_bump_view(guild_id: int, session: dict = Depends(require_guild_member)):
    """Everything a plain member's server page needs, in one round trip.

    The dashboard is an admin tool. For somebody without panel access there are
    exactly two honest things to say about a server: the bump countdowns, if
    they are one of the people who bump it, or that this place is where admins
    set the bot up and holds nothing for them. This endpoint answers which.

    Gating is membership (``require_guild_member``), not panel tier - the whole
    point is that a plain member reaches it. The timings are guild-public: the
    bot posts the same countdowns into the server's bump channel where every
    member can read them, so sharing them with a member reveals nothing they
    could not already see in Discord. The role check decides RELEVANCE, not
    secrecy, which is why an unanswered check costs the member nothing worse
    than an honest "could not check".

    Nothing manager-only leaves here, per this module's rule: bot display names,
    booleans and unix timestamps only - no channel id, no role id, no message
    text, no admin role list. ``configured`` is a bare yes/no about whether the
    server has a bump channel and a role at all, which the bump channel itself
    already tells anyone who looks.

    The three fields are independently honest. ``holds_bump_role`` is null when
    the roles lookup did not resolve; ``timers`` is null when the timings could
    not be computed. Neither null may be drawn as an empty or negative answer.
    """
    gcm = await get_guild_config_manager(db_manager)
    config = await gcm.get_config(guild_id)

    # Both of the things the reminder cannot run without. Either one missing and
    # there are no countdowns for anybody, which is a different sentence from
    # "you are not on the bump crew".
    configured = bool(config.bump_channel) and bool(config.bump_role)

    # The timings come out of the config document already in hand, so unlike the
    # role check they need no second network call. The guard is for a malformed
    # stored timestamp or delay: one bad value should cost the member the
    # timings only, and read as unknown rather than as "no bots are tracked".
    stats: dict | None
    try:
        stats = stats_service.guild_bump_stats(config)
    except Exception:
        logger.warning(
            "bump timings could not be computed for guild %s", guild_id, exc_info=True
        )
        stats = None

    if stats is None:
        timers = None
        server_time = int(time.time())
    else:
        server_time = int(stats["server_time"])
        timers = [
            {
                "bot": bot["name"],
                "ready_now": bot["status"] == "ready",
                # Only a bot that is still cooling down has a time to name. A
                # bot that is ready (including one that has never been bumped,
                # which has no cooldown running) reports null rather than a
                # made-up moment in the past.
                "ready_at": None if bot["status"] == "ready" else bot["next_due"],
            }
            for bot in stats["bots"]
        ]

    return {
        "holds_bump_role": await _holds_bump_role(config, session, guild_id),
        "timers": timers,
        "configured": configured,
        # The browser's clock cannot be trusted to say whether a cooldown has
        # expired, so every countdown on the page is anchored to this instead.
        "server_time": server_time,
    }
