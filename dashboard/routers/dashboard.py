"""Dashboard API routes - user info, guild listing, channels/roles, public stats.

Adapted to ImperialReminder: access is admin-only, granted by the Discord
MANAGE_GUILD permission or a configured panel-access role (there is no Mod
tier). Discord API results are cached with short TTLs and single-flight locks
to avoid 429s.
"""

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from dashboard._engine.discord_cache import discord_cache
from dashboard.auth.dependencies import get_current_user
from dashboard.auth.panel_role import require_panel_access, resolve_panel_role
from dashboard.config import BOT_TOKEN, MANAGE_GUILD_PERMISSION
from dashboard.services import stats as stats_service
from storage.config_manager import get_guild_config_manager
from storage.settings.collections import db_manager
from storage.sub_systems.bump_config import (
    BOT_DISPLAY_NAMES,
    BUMP_BOTS,
    BUMP_BOTS_CHOICES,
    SUPPORTED_BOTS,
)
from storage.log import get_logger

logger = get_logger("dashboard.routers.dashboard")

router = APIRouter(tags=["dashboard"])

_CONFIG_COLLECTION = "settings_guild_data"
_ADMIN_PROBE_LIMIT = 25

# Bot invite permissions: View Channels + Send Messages + Embed Links +
# Read Message History + Mention Everyone.
# Read Message History is not optional: bump detection refetches a WeBump message
# after it is edited, falls back to a refetch on an empty payload, and cleans up
# stale timer embeds. Without it all three fail quietly, so a server invited from
# here would just never get reminders.
_INVITE_PERMISSIONS = 0x400 | 0x800 | 0x4000 | 0x10000 | 0x20000  # 215040


def _has_manage(guild: dict) -> bool:
    perms = int(guild.get("permissions", 0))
    return (perms & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION


@router.get("/me")
async def me(session: dict = Depends(get_current_user)):
    """Return the current user's profile plus panel-access flags.

    Mirrors the sibling dashboards: probe configured panel roles across
    bot-present session guilds. admin = MANAGE_GUILD anywhere OR an admin role
    anywhere. There is no Mod tier, so Settings access IS admin access.
    """
    user = session["user_data"]
    can_manage_any = any(_has_manage(g) for g in session.get("guilds", []))

    bot_guild_ids = await _fetch_bot_guild_ids()
    candidate_ids = [
        g["id"] for g in session.get("guilds", []) if g["id"] in bot_guild_ids
    ][:_ADMIN_PROBE_LIMIT]
    # Guild-list probe: session-snapshot MANAGE_GUILD is fine here (no live
    # bot-token call per guild); access-gated routes verify live.
    results = await asyncio.gather(
        *(resolve_panel_role(session, gid, verify_manage_live=False) for gid in candidate_ids),
        return_exceptions=True,
    )
    roles = [r for r in results if isinstance(r, str)]
    can_access_admin_any = can_manage_any or any(r == "admin" for r in roles)

    return {
        "id": user["id"],
        "username": user.get("username"),
        "global_name": user.get("global_name"),
        "avatar": user.get("avatar"),
        "discriminator": user.get("discriminator"),
        "can_manage_any": can_manage_any,
        "can_access_admin_any": can_access_admin_any,
        # The panel is admin-only, so Settings access IS admin access.
        "can_access_settings_any": can_access_admin_any,
    }


async def _fetch_bot_guild_ids() -> set[str]:
    """The set of guild IDs the bot is currently in (engine TTL + single-flight cache)."""
    return await discord_cache.bot_guild_ids()


async def _guild_ids_with_config(guild_ids: list[str]) -> set[str]:
    """Return which of the given guild IDs have an existing config doc."""
    if not guild_ids:
        return set()
    try:
        coll = db_manager.get_collection_manager(_CONFIG_COLLECTION)
        docs = await coll.find_many(
            {"_id": {"$in": [str(gid) for gid in guild_ids]}},
            projection={"_id": 1},
        )
        return {str(doc["_id"]) for doc in docs}
    except Exception:
        logger.warning("has_config lookup failed", exc_info=True)
        return set()


@router.get("/guilds")
async def guilds(session: dict = Depends(get_current_user)):
    """Return the user's guilds, with bot status and panel-role tier.

    Shows a guild if the user holds MANAGE_GUILD (admin - even when the bot is
    absent, so they can invite it), holds a configured panel-access role in a
    guild the bot is in, or is simply a member of a guild the bot is in. Plain
    members get ``panel_role: "none"`` and the member view of that server.
    Guilds where the user is a plain member AND the bot is absent are dropped:
    there is nothing to show for them.
    """
    session_guilds = session.get("guilds", [])
    if not session_guilds:
        return []

    ids = [g["id"] for g in session_guilds]
    bot_guild_ids, configured_ids = await asyncio.gather(
        _fetch_bot_guild_ids(), _guild_ids_with_config(ids)
    )

    probe_targets = [gid for gid in ids if gid in bot_guild_ids]
    # Guild-list probe: session-snapshot MANAGE_GUILD (see /me note above).
    role_results = await asyncio.gather(
        *(resolve_panel_role(session, gid, verify_manage_live=False) for gid in probe_targets),
        return_exceptions=True,
    )
    panel_roles = {
        gid: (r if isinstance(r, str) else "none")
        for gid, r in zip(probe_targets, role_results)
    }

    out: list[dict] = []
    for guild in session_guilds:
        gid = guild["id"]
        has_manage = _has_manage(guild)
        panel_role = panel_roles.get(gid, "none")
        bot_present = gid in bot_guild_ids
        if not has_manage and panel_role == "none" and not bot_present:
            continue
        out.append({
            "id": gid,
            "name": guild["name"],
            "icon": guild.get("icon"),
            "bot_in_guild": bot_present,
            "has_config": gid in configured_ids,
            "setup_required": not bot_present,
            "panel_role": panel_role if panel_role != "none" else ("admin" if has_manage else "none"),
        })
    return out


@router.get("/bot-invite-url")
async def bot_invite_url():
    """Return the ImperialReminder bot invite URL with required permissions."""
    bot_id = await discord_cache.bot_id()
    if not bot_id:
        return {"url": None}

    url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={bot_id}"
        f"&permissions={_INVITE_PERMISSIONS}"
        f"&scope=bot%20applications.commands"
    )
    return {"url": url}


@router.get("/bump-bots")
async def bump_bots():
    """Return the supported bump bots, their display names and their cooldowns.

    ``choices`` is the same table the in-Discord panel offers, so the dashboard
    cannot present a cooldown the panel would not - and cannot invent one the
    listing service does not honour. Most services have exactly one choice; a
    couple offer a shorter wait as a second option.
    """
    return [
        {
            "key": key,
            "name": BOT_DISPLAY_NAMES.get(key, key.title()),
            "default_cooldown": int(BUMP_BOTS[key]),
            "choices": [
                {
                    "label": label,
                    "seconds": int(seconds),
                }
                for label, seconds in BUMP_BOTS_CHOICES.get(key, {}).items()
            ],
        }
        for key in SUPPORTED_BOTS
    ]


@router.get("/guilds/{guild_id}/channels")
async def guild_channels(guild_id: str, _session: dict = Depends(require_panel_access)):
    """Return text channels for a guild (engine cache, 60s TTL)."""
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Bot token not configured")
    return await discord_cache.guild_text_channels(guild_id)


@router.get("/guilds/{guild_id}/roles")
async def guild_roles(guild_id: str, _session: dict = Depends(require_panel_access)):
    """Return assignable roles for a guild (engine cache, 60s TTL)."""
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Bot token not configured")
    return await discord_cache.guild_roles(guild_id)


# ── Public stats (unauthenticated, cached) ───────────────────────────────

_CACHE_TTL = 300.0
_stats_cache: dict[str, object] = {"data": None, "ts": 0.0}


@router.get("/stats/public")
async def public_stats():
    """Public ecosystem counts for the login hero (cached 5 min)."""
    now = time.monotonic()
    data = _stats_cache["data"]
    if data is None or now - float(_stats_cache["ts"]) >= _CACHE_TTL:
        try:
            data = await stats_service.public_stats()
            _stats_cache["data"] = data
            _stats_cache["ts"] = now
        except Exception:
            logger.warning("public_stats compute failed", exc_info=True)
            if data is None:
                return JSONResponse(status_code=503, content={"detail": "stats unavailable"})
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=60"})


@router.get("/guilds/{guild_id}/bump-stats")
async def guild_bump_stats(guild_id: int, _session: dict = Depends(require_panel_access)):
    """Per-bot bump status for a guild (last bump, cooldown, next due, status)."""
    gcm = await get_guild_config_manager(db_manager)
    config = await gcm.get_config(guild_id)
    return stats_service.guild_bump_stats(config)
