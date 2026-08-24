"""Guild overview API - everything the dashboard home renders, in one round trip.

Gated on ``require_panel_access``, the same dependency every other per-guild
route in this dashboard uses: MANAGE_GUILD verified live, or a role from
``roles.admin_role_ids``. There is no Mod tier here, so this is admin-only.

Read-only. The four sections are built concurrently and EACH one is allowed to
fail on its own - a section that raises is logged and returned as ``null``,
which is exactly why every section is nullable in the frontend contract. One
broken collection must not blank the page.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from dashboard.auth.panel_role import require_panel_access
from dashboard.services import overview as overview_service
from storage.config_manager import get_guild_config_manager
from storage.settings.collections import db_manager
from storage.log import get_logger

logger = get_logger("dashboard.routers.overview")

router = APIRouter(tags=["overview"])

#: Section name -> the key it occupies in the response, in gather order.
_SECTIONS = ("bumps", "setup", "changes")


@router.get("/guilds/{guild_id}/overview")
async def guild_overview(guild_id: int, _session: dict = Depends(require_panel_access)):
    """Return a ``GuildOverview`` for one guild."""
    gcm = await get_guild_config_manager(db_manager)
    config = await gcm.get_config(guild_id)
    async def bumps():
        return overview_service.build_bumps(config)

    async def setup():
        return overview_service.build_setup(config)

    results = await asyncio.gather(
        bumps(),
        setup(),
        overview_service.build_changes(guild_id),
        return_exceptions=True,
    )

    sections: dict[str, dict | None] = {}
    for name, result in zip(_SECTIONS, results):
        if isinstance(result, BaseException):
            logger.warning(
                "Overview section '%s' failed for guild %s", name, guild_id,
                exc_info=result,
            )
            sections[name] = None
        else:
            sections[name] = result

    try:
        features = overview_service.build_features(config, **sections)
    except Exception:
        # features is not nullable in the contract, so an empty rail is the only
        # shape available here. It is logged loudly because an empty rail on a
        # configured guild is a bug, not a state the data can produce.
        logger.error("Overview feature rail failed for guild %s", guild_id, exc_info=True)
        features = []

    return {
        "guild_id": str(guild_id),
        "server_time": overview_service.server_time(),
        "features": features,
        **sections,
    }
