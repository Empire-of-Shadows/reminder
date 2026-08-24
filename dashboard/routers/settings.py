from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from dashboard.auth.dependencies import get_current_user
from dashboard.auth.panel_role import resolve_panel_role, require_panel_access
from dashboard._engine.auth.csrf import verify_csrf
from dashboard.services import stats as stats_service
from storage.audit_log import get_audit_log_manager
from storage.settings.collections import db_manager
from storage.config_manager import get_guild_config_manager, GuildConfig
from storage.sub_systems.bump_config import (
    BUMP_BOTS,
    BUMP_BOTS_CHOICES,
    SUPPORTED_BOTS,
)
from storage.log import get_logger

logger = get_logger("dashboard.routers.settings")
router = APIRouter(tags=["settings"])

# Discord snowflake IDs are 64-bit and exceed JS's safe-integer range, so they
# must cross the wire as strings (JSON numbers would lose precision in the
# browser). They are stored as ints in Mongo (the bot needs ints for the Discord
# API), so we stringify on the way out and parse back to int on the way in.
_ID_FIELDS = ("bump_channel", "bump_role", "timers_channel")
_ALLOWED_KEYS = {
    "bump_channel", "bump_role", "enabled_bots",
    "timers_channel", "timers_message", "custom_message",
    "roles", "bot_delay",
}

#: Which settings-page section a changed key belongs to, for the audit trail.
#: ``bot_delay.<bot>`` is handled separately; everything else is a flat key.
_KEY_SECTIONS = {
    "bump_channel": "bumps",
    "bump_role": "bumps",
    "enabled_bots": "bots",
    "timers_channel": "timers",
    "timers_message": "timers",
    "custom_message": "message",
    "roles": "access",
}


async def _validate_guild_ids(guild_id: int, updates: dict) -> None:
    """Reject channel/role snowflakes that don't belong to this guild.

    Uses the cached guild channel/role fetchers. Fails open when the fetch
    comes back empty (Discord unreachable) so an API hiccup never blocks a
    legitimate save - the bot degrades gracefully on foreign ids anyway.
    """
    from dashboard.routers.dashboard import guild_channels, guild_roles

    channel_keys = [k for k in ("bump_channel", "timers_channel") if updates.get(k)]
    if channel_keys:
        channels = await guild_channels(str(guild_id))
        valid_channels = {str(c["id"]) for c in channels}
        if valid_channels:
            for k in channel_keys:
                if str(updates[k]) not in valid_channels:
                    raise HTTPException(
                        status_code=422, detail=f"{k} is not a channel in this guild"
                    )

    role_cfg = updates.get("roles") or {}
    wants_roles = bool(updates.get("bump_role")) or bool(role_cfg.get("admin_role_ids"))
    if wants_roles:
        roles = await guild_roles(str(guild_id))
        valid_roles = {str(r["id"]) for r in roles}
        if valid_roles:
            if updates.get("bump_role") and str(updates["bump_role"]) not in valid_roles:
                raise HTTPException(
                    status_code=422, detail="bump_role is not a role in this guild"
                )
            if any(str(r) not in valid_roles for r in role_cfg.get("admin_role_ids", [])):
                raise HTTPException(
                    status_code=422,
                    detail="roles.admin_role_ids contains a role not in this guild",
                )


def _coerce_id(value) -> int:
    """Parse an incoming ID (string/number/None) to an int; 0 means unset."""
    if value in (None, "", 0, "0"):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalized_roles(raw) -> dict:
    """The canonical wire shape for the panel-access role list."""
    raw = raw if isinstance(raw, dict) else {}
    return {"admin_role_ids": [str(r) for r in (raw.get("admin_role_ids") or [])]}


def _coerce_bot_delay(value) -> dict[str, int]:
    """Validate an incoming ``bot_delay`` map into ``{bot: seconds}``.

    Two separate checks, and both matter. The key must be a bot this bot
    actually supports, and the value must be one of the cooldowns offered for
    THAT bot (``BUMP_BOTS_CHOICES``) - a free-typed number here would let the
    dashboard schedule a reminder shorter than the listing service's real
    cooldown, so every reminder after it would be for a bump that cannot be
    made.
    """
    value = value if isinstance(value, dict) else {}
    out: dict[str, int] = {}
    for bot, raw in value.items():
        bot = str(bot)
        if bot not in SUPPORTED_BOTS:
            raise HTTPException(
                status_code=422, detail=f"'{bot}' is not a supported bump bot"
            )
        try:
            seconds = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail=f"bot_delay.{bot} must be a number of seconds"
            )
        allowed = set(BUMP_BOTS_CHOICES.get(bot, {}).values())
        if seconds not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"bot_delay.{bot} is not one of the cooldowns offered for that bot",
            )
        out[bot] = seconds
    return out


def _old_value(config: GuildConfig, key: str) -> Any:
    """The stored value a proposed update would replace, in the update's own shape."""
    if key.startswith("bot_delay."):
        bot = key.split(".", 1)[1]
        delays = config.bot_delay or {}
        return int(delays.get(bot, BUMP_BOTS.get(bot, 0)) or 0)
    if key == "roles":
        return _normalized_roles(config.roles)
    return getattr(config, key, None)


def _serialize(config: GuildConfig, panel_role: str) -> dict:
    """Config dict with snowflake IDs as strings ('' when unset)."""
    data = config.to_dict()
    for key in _ID_FIELDS:
        val = data.get(key) or 0
        data[key] = str(val) if val else ""
    # Role-id lists travel as strings too.
    data["roles"] = _normalized_roles(data.get("roles"))
    data["panel_role"] = panel_role
    return data


@router.get("/guilds/{guild_id}/settings")
async def get_settings(guild_id: int, session: dict = Depends(require_panel_access)):
    role = await resolve_panel_role(session, str(guild_id))
    gcm = await get_guild_config_manager(db_manager)
    config = await gcm.get_config(guild_id)
    return _serialize(config, role)


@router.put("/guilds/{guild_id}/settings")
async def update_settings(
    guild_id: int,
    patch: dict,
    session: dict = Depends(require_panel_access),
    _csrf: None = Depends(verify_csrf),
):
    role = await resolve_panel_role(session, str(guild_id))
    # Admin-only surface: require_panel_access already rejects "none", so this is
    # defense in depth against a future tier ever being added.
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    gcm = await get_guild_config_manager(db_manager)
    # Read before writing: the audit trail needs the value each change replaced,
    # and "unchanged" has to be decidable so a save that touched nothing does
    # not fill the history with entries nobody made.
    before = await gcm.get_config(guild_id)

    # Build a whitelisted partial update and write it as one surgical $set.
    # Never replace the whole document: the bot process writes timestamps concurrently, and a full-document write from a cached
    # snapshot would silently clobber them.
    updates: dict = {}
    for key, value in patch.items():
        if key not in _ALLOWED_KEYS:
            continue
        if key in _ID_FIELDS:
            updates[key] = _coerce_id(value)
        elif key == "enabled_bots":
            bots = value if isinstance(value, list) else []
            updates[key] = [str(b) for b in bots if str(b) in SUPPORTED_BOTS]
        elif key == "timers_message":
            updates[key] = bool(value)
        elif key == "custom_message":
            updates[key] = str(value or "")
        elif key == "roles":
            updates[key] = _normalized_roles(value)
        elif key == "bot_delay":
            # Per-bot cooldowns are written as dotted leaves so saving one bot's
            # cooldown never rewrites another's.
            for bot, seconds in _coerce_bot_delay(value).items():
                updates[f"bot_delay.{bot}"] = seconds

    if updates:
        await _validate_guild_ids(guild_id, updates)
        if not await gcm.set_values(guild_id, updates):
            raise HTTPException(status_code=500, detail="Failed to save settings")
        await _audit_changes(guild_id, session, before, updates)

    config = await gcm.get_config(guild_id)
    return _serialize(config, role)


async def _audit_changes(
    guild_id: int, session: dict, before: GuildConfig, updates: dict
) -> None:
    """Record one audit entry per key this save actually changed.

    Until this existed the in-Discord panel wrote to the audit log and the
    dashboard did not, so a server's change history quietly omitted every edit
    made on the web - and so did the privacy export built on the same records.
    ``source`` distinguishes the two writers.

    Best-effort by design: a save that succeeded must not be reported as failed
    because the trail could not be appended.
    """
    changed = [
        (key, value)
        for key, value in updates.items()
        if _old_value(before, key) != value
    ]
    if not changed:
        return

    user_data = session.get("user_data") or {}
    actor_id = user_data.get("id") or session.get("user_id")
    if actor_id is None:
        return
    actor_name = (
        user_data.get("global_name")
        or user_data.get("username")
        or str(actor_id)
    )

    try:
        audit = get_audit_log_manager(db_manager)
    except Exception:
        logger.warning("audit log unavailable for guild %s", guild_id, exc_info=True)
        return

    for key, value in changed:
        section = (
            "cooldowns" if key.startswith("bot_delay.") else _KEY_SECTIONS.get(key, "")
        )
        try:
            await audit.log_config_change(
                guild_id=guild_id,
                actor_id=actor_id,
                actor_name=actor_name,
                action="set",
                section=section,
                key=key,
                old_value=_old_value(before, key),
                new_value=value,
                source="dashboard",
            )
        except Exception:
            logger.warning(
                "audit entry failed for guild %s key %s", guild_id, key, exc_info=True
            )
