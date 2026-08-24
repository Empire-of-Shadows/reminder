"""ImperialReminder - admin engine bindings (the per-bot seam).

The vendored engine (``admin_cog.py``) is byte-identical across every bot; it reaches all of
ImperialReminder's backends through the names defined here. See
``admin_engine/bindings_reference.py`` for the full contract.

Every persistence path flows through the bot's existing managers (which themselves write via
the shared ``db_manager``'s collection managers): per-guild config through
``GuildConfigManager`` (canonical ``roles`` shape + an ``extra_data`` catch-all),
audit entries through ``storage/audit_log.py``. Nothing here opens its own collection handle.

ImperialReminder's ``panel_configs.py`` binds its leaves to inline ``GuildConfigManager``
accessors, so the generic ``config_*`` / ``db_*`` doers below exist for engine contract
completeness and for the shared role resolver.
"""

from __future__ import annotations

from typing import Any, Optional

import discord

from storage.config_manager import get_guild_config_manager
from storage.audit_log import get_audit_log_manager
from storage.log import get_logger

# Re-export the static branding text the engine reads by name.
from .panel_branding import OVERVIEW_FOOTER, SETUP_GUIDE_TEXT

logger = get_logger("AdminBindings")


# ── Static configuration ────────────────────────────────────────────────────────

BOT_NAME = "Imperial Reminder"

# Breadcrumb the engine's setup notices use when telling an owner where to delegate
# panel access. This bot's node sits at the panel's top level (no wrapping "Panel
# Access" menu), so the engine default ("Role Configuration") would point at a node
# that does not exist.
ROLE_ACCESS_PATH = "Panel Access Roles"

# The panel is admin-only: there is no Mod tier. resolve_panel_role below collapses
# anything that is not "admin" to "none". The engine's mod machinery
# (`PanelNode.mod_allowed`, the `MOD_ALLOWED_CATEGORIES` fallback) was REMOVED
# fleet-wide on 2026-08-06 - those names no longer exist anywhere, so do not go
# looking for them.

# OVERVIEW_FOOTER / SETUP_GUIDE_TEXT are re-exported from panel_branding above.


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _dig(config: Any, path: str, default: Any = None) -> Any:
    """Read a dotted ``path`` off a GuildConfig: first segment is a dataclass attribute
    (falling back to ``extra_data`` for dynamic keys like ``hide_setup_guide``); deeper
    segments index dicts (``roles.admin_role_ids``)."""
    parts = path.split(".")
    node = getattr(config, parts[0], None)
    if node is None and hasattr(config, "extra_data"):
        node = config.extra_data.get(parts[0])
    for p in parts[1:]:
        if isinstance(node, dict):
            node = node.get(p)
        else:
            node = getattr(node, p, None)
        if node is None:
            return default
    return default if node is None else node


async def _cm(collection: str):
    """An engine CollectionManager from the shared db_manager (reused via the config mgr)."""
    mgr = await get_guild_config_manager()
    return mgr.db_manager.get_collection_manager(collection)


# ── Tier resolution ──────────────────────────────────────────────────────────────

async def resolve_panel_role(user: discord.Member, guild_id: int) -> str:
    """Return "admin" | "none" - the ImperialReminder panel has no Mod tier.

    Delegates to the engine's generic resolver (``auth.resolve_panel_role_from_config``)
    for the Manage Server + ``roles.admin_role_ids`` checks, then collapses any non-admin
    outcome to "none". A stale ``roles.mod_role_ids`` value in an old document therefore
    grants nothing. With no admin roles configured, Manage Server is the only path in.
    """
    from ..auth import resolve_panel_role_from_config
    role = await resolve_panel_role_from_config(user, guild_id)
    return role if role == "admin" else "none"


# ── Dashboard flags (setup-guide toggle, etc.) ───────────────────────────────────

async def get_setting(key: str, guild_id: int, default: Any = None):
    return await config_get(guild_id, key, default)


async def set_setting(key: str, value: Any, guild_id: int) -> None:
    await config_set(guild_id, key, value)


# ── Premium ──────────────────────────────────────────────────────────────────────

async def is_premium(guild_id: int) -> bool:
    """ImperialReminder is 100% free (premium removed 2026-08-24): every feature is
    available to every server. The vendored engine imports this symbol by name
    (``admin_cog`` gates ``premium_values`` options through it), so it must exist -
    and it answers True so nothing is ever locked."""
    return True


# ── Cache invalidation ───────────────────────────────────────────────────────────

def invalidate_caches(guild_id: int) -> None:
    """Drop this guild's cached GuildConfig (set_value already invalidates on write; this
    also covers out-of-band edits)."""
    try:
        from storage import config_manager as _cm_mod
        mgr = _cm_mod._guild_config_manager
        if mgr:
            mgr.invalidate(int(guild_id))
    except Exception as e:  # best-effort: never block a save
        logger.debug(f"invalidate_caches skipped for {guild_id}: {e}")


# ── Audit log ────────────────────────────────────────────────────────────────────

async def audit_log_entry(
    *,
    guild_id: int,
    actor_id: int,
    actor_name: str,
    section: str,
    key: str,
    old_value: object,
    new_value: object,
    action: str,
) -> None:
    try:
        al = get_audit_log_manager()
    except Exception:
        return  # audit not initialized; failures are swallowed by the engine anyway
    await al.log(
        guild_id=int(guild_id),
        user_id=int(actor_id),
        action=f"{action}:{section}.{key}",
        details={
            "actor_name": actor_name,
            "section": section,
            "key": key,
            "old_value": old_value,
            "new_value": new_value,
        },
    )


# ── Config access (dotted-path over GuildConfig) ─────────────────────────────────

async def config_get(guild_id: int, path: str, default=None):
    cm = await get_guild_config_manager()
    cfg = await cm.get_config(int(guild_id))
    return _dig(cfg, path, default)


async def config_set(guild_id: int, path: str, value) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(int(guild_id), path, value)


async def config_unset(guild_id: int, path: str) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(int(guild_id), path, None)


# ── Collection access (over the shared db_manager's CollectionManagers) ───────────

async def db_find(collection: str, query: dict, *, sort=None, limit: int | None = None) -> list[dict]:
    return await (await _cm(collection)).find_many(query, sort=sort, limit=limit)


async def db_count(collection: str, query: dict) -> int:
    return await (await _cm(collection)).count_documents(query)


async def db_delete_one(collection: str, query: dict) -> bool:
    return await (await _cm(collection)).delete_one(query)


async def db_delete_many(collection: str, query: dict) -> int:
    return await (await _cm(collection)).delete_many(query)


async def db_update_one(collection: str, query: dict, update: dict, *, upsert: bool = False) -> bool:
    return await (await _cm(collection)).update_one(query, update, upsert=upsert)


async def db_insert_one(collection: str, doc: dict):
    return await (await _cm(collection)).create_one(doc)
