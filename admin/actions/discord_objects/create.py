# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Create Discord entities (role / channel) - thin, reusable wrappers."""

from __future__ import annotations

import logging
import re
from typing import Optional

import discord

logger = logging.getLogger("AdminActions.discord")

# -- Name validation (standard §11) --------------------------------------------

_RESERVED_ROLE_NAMES = {"everyone", "@everyone", "here", "@here"}
_TEXT_CHANNEL_NAME_RE = re.compile(r"^[a-z0-9-]+$")


def _basic_name(raw: str, what: str):
    name = (raw or "").strip()
    if not name:
        return False, None, f"{what} name cannot be empty."
    if len(name) > 100:
        return False, None, f"{what} name must be 100 characters or fewer."
    return True, name, ""


def validate_role_name(raw: str):
    """``(ok, name, error)`` - non-empty, <= 100 chars, not a Discord-reserved name."""
    ok, name, error = _basic_name(raw, "Role")
    if not ok:
        return ok, name, error
    if name.lower() in _RESERVED_ROLE_NAMES:
        return False, None, "That name is reserved by Discord. Pick another name."
    return True, name, ""


def validate_channel_name(raw: str):
    """``(ok, name, error)`` - the fleet rule for TEXT channel names: lowercase
    letters, digits, and "-" only, <= 100 chars. Fixable input is normalized
    rather than rejected: capitals are lowered, spaces become "-", and "-" runs
    are collapsed, so ``name`` may differ from ``raw``. Only characters that
    cannot be converted produce an error, and the error names them. Voice
    channels and categories are display names (Discord allows spaces and case
    there) and use the basic check instead."""
    ok, name, error = _basic_name(raw, "Channel")
    if not ok:
        return ok, name, error
    name = re.sub(r"\s+", "-", name.lower())
    name = re.sub(r"-{2,}", "-", name).strip("-")
    if not name:
        return False, None, "Channel name must include at least one letter or number."
    if not _TEXT_CHANNEL_NAME_RE.fullmatch(name):
        bad = ", ".join(
            f'"{ch}"' for ch in sorted({c for c in name if not _TEXT_CHANNEL_NAME_RE.fullmatch(c)})
        )
        return False, None, (
            'Channel names can only use lowercase letters, numbers, and "-" '
            "(spaces and capitals are converted automatically). "
            f"Remove: {bad}."
        )
    return True, name, ""


def validator_for_channel_kind(kind: str):
    """The §11 name validator for a channel ``kind``: text channels get the
    lowercase/"-" fleet rule; voice channels and categories are display names
    and get the basic (non-empty, <= 100 chars) check."""
    if kind == "text":
        return validate_channel_name
    return lambda raw: _basic_name(raw, "Category" if kind == "category" else "Channel")


def channel_kind_for_types(channel_types) -> str:
    """Map a ``PanelNode.channel_types`` filter to the create ``kind``.

    The created channel must be one the picker itself ACCEPTS: a filter of
    only categories creates a category, a filter of only voice kinds (voice
    and/or stage) creates a voice channel, and anything else - no filter, or
    a list that admits text - creates a text channel. The old rule matched
    single-type filters only, so a voice+stage picker fell through to TEXT
    and minted a channel its own picker could not select (found live
    2026-08-28 on ecom's voice Disabled Channels picker)."""
    if channel_types:
        names = {getattr(t, "name", "") for t in channel_types}
        if names and names <= {"category"}:
            return "category"
        if names and names <= {"voice", "stage_voice"}:
            return "voice"
    return "text"


async def create_role(guild: discord.Guild, name: str, *, reason: str = "Admin panel", **kwargs) -> Optional[discord.Role]:
    """Create a guild role; returns it (or None on failure)."""
    try:
        return await guild.create_role(name=name, reason=reason, **kwargs)
    except discord.HTTPException as exc:
        logger.warning("create_role failed for %r: %s", name, exc)
        return None


async def create_channel(guild: discord.Guild, name: str, *, kind: str = "text",
                         reason: str = "Admin panel", **kwargs):
    """Create a guild channel (``kind`` = "text" | "voice" | "category"); returns it or None."""
    factory = {
        "text": guild.create_text_channel,
        "voice": guild.create_voice_channel,
        "category": guild.create_category,
    }.get(kind, guild.create_text_channel)
    try:
        return await factory(name=name, reason=reason, **kwargs)
    except discord.HTTPException as exc:
        logger.warning("create_channel failed for %r: %s", name, exc)
        return None


# -- Create-and-store action factories ----------------------------------------
# Thin wrappers over modal_action: open a modal for a name, create the entity, then
# persist its id to a config path. Generalizes Ecom's "Create Active Role" flow.

def create_role_action(
    key, *, label, store_path, name_label="Role name", description="",
    reason="Admin panel", premium_label=None, **role_kwargs,
):
    """An ``action`` node: prompt for a role name, create the role, store its id at
    config ``store_path``. Extra kwargs pass through to ``guild.create_role``.

    Per standard §11 the open button first checks the bot's Manage Roles server
    permission, and the name is validated with retry-with-input-kept on failure."""
    from ..structure.modals import modal_action
    from ..config.fields import set_config_field
    from ...permission_checks import check_bot_guild_permission

    async def _submit(guild, raw):
        role = await create_role(guild, raw, reason=reason, **role_kwargs)
        if role is None:
            raise RuntimeError("role creation failed")
        await set_config_field(guild.id, store_path, role.id)
        return role

    return modal_action(
        key, label=label, description=description, field_label=name_label,
        on_submit=_submit, success_text=lambda r: f"Created and saved {r.mention}.",
        permission_check=lambda g: check_bot_guild_permission(g, "manage_roles"),
        validator=validate_role_name,
        premium_label=premium_label,
    )


def create_channel_action(
    key, *, label, store_path, kind="text", name_label="Channel name", description="",
    reason="Admin panel", premium_label=None, **channel_kwargs,
):
    """An ``action`` node: prompt for a channel name, create the channel (``kind`` =
    "text" | "voice" | "category"), store its id at config ``store_path``.

    Per standard §11 the open button first checks the bot's Manage Channels server
    permission; text-channel names get the lowercase/"-" fleet rule, with
    retry-with-input-kept on failure."""
    from ..structure.modals import modal_action
    from ..config.fields import set_config_field
    from ...permission_checks import check_bot_guild_permission

    async def _submit(guild, raw):
        channel = await create_channel(guild, raw, kind=kind, reason=reason, **channel_kwargs)
        if channel is None:
            raise RuntimeError("channel creation failed")
        await set_config_field(guild.id, store_path, channel.id)
        return channel

    name_validator = validator_for_channel_kind(kind)
    return modal_action(
        key, label=label, description=description, field_label=name_label,
        on_submit=_submit, success_text=lambda c: f"Created and saved {c.mention}.",
        permission_check=lambda g: check_bot_guild_permission(g, "manage_channels"),
        validator=name_validator,
        premium_label=premium_label,
    )
