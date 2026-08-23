# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""TTL + single-flight caches for bot-token Discord API reads.

Promoted from the near-identical blocks in TheCodex's and ImperialReminder's
``routers/dashboard.py``: every dashboard needs the same four reads (which guilds
is the bot in, the bot's own id for the invite URL, a guild's text channels, a
guild's assignable roles), each cached with a short TTL and a single-flight lock
so concurrent requests cannot stampede the Discord API into 429s.

Reads bot credentials from the seam (``config.BOT_TOKEN`` / ``config.DISCORD_API_BASE``)
at call time. All methods are fail-soft: on a Discord error they log, return the
last cached value (or an empty result), and never raise - the caller decides
whether an empty result is a 503. Per-guild caches are BOUNDED (oldest-entry
eviction) so a many-guild deployment cannot grow them without limit.

Usage (in a bot's ``routers/dashboard.py``)::

    from dashboard._engine.discord_cache import discord_cache

    bot_guild_ids = await discord_cache.bot_guild_ids()
    channels = await discord_cache.guild_text_channels(guild_id)
    roles = await discord_cache.guild_roles(guild_id)
    bot_id = await discord_cache.bot_id()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

import httpx

from dashboard import config as _config

logger = logging.getLogger("dashboard.discord_cache")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# TTLs match the values every dashboard already used.
_GUILDS_TTL = 300.0  # bot guild list + bot id
_RESOURCE_TTL = 60.0  # per-guild channels/roles/members
_MAX_MEMBER_ENTRIES = 2000  # guild:user pairs; one page of names is a few dozen at most
_MAX_GUILD_ENTRIES = 512  # bound on the per-guild caches (oldest evicted)


def _token() -> str:
    return getattr(_config, "BOT_TOKEN", "") or ""


def _api_base() -> str:
    return getattr(_config, "DISCORD_API_BASE", "https://discord.com/api/v10")


async def _get_with_retry(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    """One GET with a single 429 retry. Returns None on non-200."""
    headers = {"Authorization": f"Bot {_token()}"}
    resp = await client.get(url, headers=headers)
    if resp.status_code == 429:
        retry_after = float(resp.headers.get("Retry-After", "2"))
        logger.info("Discord rate-limited on %s, retrying in %.1fs", url, retry_after)
        await asyncio.sleep(retry_after)
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        logger.warning("Discord GET %s failed: %s", url, resp.status_code)
        return None
    return resp


class _BoundedTTLMap:
    """guild_id -> {"data": ..., "ts": float}, evicting the oldest past a size cap."""

    def __init__(self, max_entries: int, ttl: float):
        self._map: Dict[str, Dict[str, Any]] = {}
        self._max = max_entries
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        entry = self._map.get(key)
        if entry and time.monotonic() - entry["ts"] < self._ttl:
            return entry["data"]
        return None

    def set(self, key: str, data: Any) -> None:
        if key not in self._map and len(self._map) >= self._max:
            oldest = min(self._map, key=lambda k: self._map[k]["ts"])
            self._map.pop(oldest, None)
        self._map[key] = {"data": data, "ts": time.monotonic()}


class DiscordApiCache:
    """The four shared bot-token reads, TTL-cached and single-flighted."""

    def __init__(self):
        self._bot_guilds: Set[str] = set()
        self._bot_guilds_ts = 0.0
        self._bot_guilds_lock = asyncio.Lock()

        self._bot_id: Optional[str] = None
        self._bot_id_ts = 0.0
        self._bot_id_lock = asyncio.Lock()

        self._channels = _BoundedTTLMap(_MAX_GUILD_ENTRIES, _RESOURCE_TTL)
        self._roles = _BoundedTTLMap(_MAX_GUILD_ENTRIES, _RESOURCE_TTL)
        # Single-member lookups, keyed "guild:user". Same TTL as the other per-guild
        # resources; a miss (left the guild, bad id) is cached too so a page that shows
        # many names does not re-ask Discord for the same absent member on every render.
        self._members = _BoundedTTLMap(_MAX_MEMBER_ENTRIES, _RESOURCE_TTL)
        # Per-guild single-flight locks; pruned alongside the caches by virtue of
        # being recreated rarely (a lock per active guild, bounded in practice by
        # the caches above - stale locks are just idle asyncio.Lock objects).
        self._resource_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # -- bot guild list ---------------------------------------------------------

    async def bot_guild_ids(self) -> Set[str]:
        """The set of guild ids the bot is in (paginated; stale-on-error)."""
        if not _token():
            return set()
        now = time.monotonic()
        if self._bot_guilds and now - self._bot_guilds_ts < _GUILDS_TTL:
            return self._bot_guilds

        async with self._bot_guilds_lock:
            now = time.monotonic()
            if self._bot_guilds and now - self._bot_guilds_ts < _GUILDS_TTL:
                return self._bot_guilds

            guild_ids: Set[str] = set()
            after = "0"
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                while True:
                    url = f"{_api_base()}/users/@me/guilds?limit=200&after={after}"
                    resp = await _get_with_retry(client, url)
                    if resp is None:
                        return self._bot_guilds or guild_ids
                    guilds = resp.json()
                    if not guilds:
                        break
                    for g in guilds:
                        guild_ids.add(g["id"])
                    if len(guilds) < 200:
                        break
                    after = guilds[-1]["id"]

            self._bot_guilds = guild_ids
            self._bot_guilds_ts = now
            return guild_ids

    # -- bot id (invite URL) ----------------------------------------------------

    async def bot_id(self) -> Optional[str]:
        """The bot's own user id (for building the invite URL). None on failure."""
        if not _token():
            return None
        now = time.monotonic()
        if self._bot_id and now - self._bot_id_ts < _GUILDS_TTL:
            return self._bot_id

        async with self._bot_id_lock:
            now = time.monotonic()
            if self._bot_id and now - self._bot_id_ts < _GUILDS_TTL:
                return self._bot_id
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await _get_with_retry(client, f"{_api_base()}/users/@me")
                if resp is None:
                    return self._bot_id
                self._bot_id = resp.json()["id"]
                self._bot_id_ts = now
                return self._bot_id

    # -- per-guild resources ----------------------------------------------------

    async def guild_channels(self, guild_id: str, types: tuple = (0,)) -> List[dict]:
        """Guild channels filtered to ``types``, sorted by position.

        The RAW channel list (all types, with ``parent_id``) is what's cached,
        so different callers can request different type filters (text-only
        pickers vs category+text panels like TheHost's ``game_category_id``
        select) off one fetch. Returns a NEW list per call - callers may
        re-sort freely. Empty list on failure.
        """
        guild_id = str(guild_id)
        raw = self._channels.get(guild_id)
        if raw is None:
            async with self._resource_locks[f"c:{guild_id}"]:
                raw = self._channels.get(guild_id)
                if raw is None:
                    if not _token():
                        return []
                    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                        resp = await _get_with_retry(
                            client, f"{_api_base()}/guilds/{guild_id}/channels"
                        )
                        if resp is None:
                            return []
                    raw = [
                        {
                            "id": ch["id"],
                            "name": ch["name"],
                            "type": ch["type"],
                            "parent_id": ch.get("parent_id"),
                            "position": ch.get("position", 0),
                        }
                        for ch in resp.json()
                    ]
                    self._channels.set(guild_id, raw)

        channels = [dict(ch) for ch in raw if ch["type"] in types]
        channels.sort(key=lambda c: c["position"])
        return channels

    async def guild_member(self, guild_id: str, user_id: str) -> Optional[dict]:
        """One guild member as ``{"id", "display_name", "username"}``, or ``None``.

        ``display_name`` follows discord.py's ``Member.display_name`` precedence: guild
        nickname, then global display name, then username. A plain REST fetch that
        needs no privileged intent. ``None`` when the member is not in the guild, the id
        is malformed, or Discord cannot be reached - callers fall back to whatever
        name they already hold.
        """
        guild_id = str(guild_id)
        user_id = str(user_id)
        if not user_id.isdigit():
            return None
        key = f"{guild_id}:{user_id}"
        hit = self._members.get(key)
        if hit is not None:
            return hit or None
        async with self._resource_locks[f"m:{key}"]:
            hit = self._members.get(key)
            if hit is not None:
                return hit or None
            if not _token():
                return None
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await _get_with_retry(
                    client, f"{_api_base()}/guilds/{guild_id}/members/{user_id}"
                )
            if resp is None:
                self._members.set(key, {})
                return None
            raw = resp.json()
            user = raw.get("user") or {}
            member = {
                "id": str(user.get("id") or user_id),
                "display_name": (
                    raw.get("nick") or user.get("global_name") or user.get("username") or ""
                ),
                "username": user.get("username") or "",
            }
            self._members.set(key, member)
            return member

    async def guild_text_channels(self, guild_id: str) -> List[dict]:
        """Text channels (type 0) sorted by position. Empty list on failure."""
        return await self.guild_channels(guild_id, types=(0,))

    async def guild_roles(self, guild_id: str) -> List[dict]:
        """Assignable roles (position > 0, not managed) sorted by position.
        Empty list on failure."""
        guild_id = str(guild_id)
        cached = self._roles.get(guild_id)
        if cached is not None:
            return cached

        async with self._resource_locks[f"r:{guild_id}"]:
            cached = self._roles.get(guild_id)
            if cached is not None:
                return cached
            if not _token():
                return []
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await _get_with_retry(
                    client, f"{_api_base()}/guilds/{guild_id}/roles"
                )
                if resp is None:
                    return []
            roles = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "color": r.get("color", 0),
                    "position": r.get("position", 0),
                }
                for r in resp.json()
                if r.get("position", 0) > 0 and not r.get("managed", False)
            ]
            roles.sort(key=lambda r: r["position"])
            self._roles.set(guild_id, roles)
            return roles


# Module-level singleton - one cache per dashboard process.
discord_cache = DiscordApiCache()
