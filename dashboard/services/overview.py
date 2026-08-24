"""Guild overview aggregation for the ImperialReminder dashboard home.

One round trip that answers "is this server's bump reminder actually doing
anything, and what did it do lately". Every section is built independently so
the router can gather them with ``return_exceptions=True`` and null out whatever
failed - one broken collection must never blank the whole page.

Read-only by design: nothing here writes, and nothing creates an index.

What this bot actually stores, and therefore what can honestly be reported:

  - ``settings_guild_data`` (``ImperialReminder.GuildData``, ``_id`` = str(guild
    id)) - the whole per-guild setup: ``enabled_bots``, ``bump_channel``,
    ``bump_role``, ``timers_channel``, ``timers_message``, ``custom_message``,
    ``roles.admin_role_ids``, ``bot_delay.<bot>`` and ``timestamps.*``.
  - ``timestamps.<bot>_timestamp`` - when that bump bot was last bumped.
    Written by ``Features/bump/detection/handler.py`` on every detected bump.
  - ``timestamps.<bot>_reminded`` - the bump timestamp the last delivered
    reminder covered (``BumpHandler._mark_reminded``). Comparing the two is the
    only record of whether a reminder actually went out for the newest bump.
  - ``audit_log`` - who changed which setting, when (TTL 365 days).

Two things are deliberately NOT reported:

  - A bump history. Only the LATEST bump timestamp per bot is stored - there is
    no per-bump record anywhere - so "bumps over time" would have to be invented.
    The one real time series in this bot is the audit trail, which is what the
    chart on the home page draws.
  - Anything per-member. ImperialReminder tracks servers, not people.

Snowflake spelling: the config document keys guilds as a STRING ``_id`` while
the admin seam writes audit entries with an INT ``guild_id`` while this dashboard
(and the retired premium cog's historical rows) write a STRING one. Every audit filter here therefore matches both spellings,
the same way ``services/user_data.py`` does.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from dashboard.services import stats as stats_service
from storage.config_manager import GuildConfig
from storage.settings.collections import db_manager
from storage.log import get_logger
from storage.sub_systems.bump_config import BOT_DISPLAY_NAMES, SUPPORTED_BOTS

logger = get_logger("dashboard.services.overview")

#: How far back the change-activity window looks.
TREND_DAYS = 30
#: Newest audit entries surfaced on the overview.
RECENT_CHANGES_LIMIT = 6

_AUDIT_COLLECTION = "audit_log"


# -- Small shared helpers ---------------------------------------------------


def _iso(value: Any) -> str | None:
    """Datetime -> ISO-8601 string. Naive values are read as UTC (that is how
    every writer in this bot stores them). Anything else becomes None."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _both_forms(value: Any) -> list[Any]:
    """The int and str spellings of a snowflake, for filters that must match both."""
    forms: list[Any] = [str(value)]
    try:
        forms.append(int(value))
    except (TypeError, ValueError):
        pass
    return forms


def _day_keys(days: int) -> list[str]:
    """The last ``days`` YYYY-MM-DD keys in UTC, oldest first, ending today."""
    end_day = datetime.now(timezone.utc).date()
    start = end_day - timedelta(days=days - 1)
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def fill_daily(counts: dict[str, int], days: int = TREND_DAYS) -> list[dict]:
    """Turn a sparse {YYYY-MM-DD: count} map into a dense day-by-day series.

    Days with nothing recorded are emitted as zero rather than skipped. A chart
    drawn from only the days that had a change reports a cadence that never
    happened.
    """
    return [{"date": key, "changes": int(counts.get(key, 0))} for key in _day_keys(days)]


# -- Bump activity ----------------------------------------------------------


def build_bumps(config: GuildConfig) -> dict:
    """``BumpsOverview`` - live per-bot bump state for this guild.

    The per-bot rows come straight from ``services/stats.guild_bump_stats`` so
    the home page and the existing ``/bump-stats`` endpoint can never drift
    apart. What is added on top is the roll-up the page needs (how many are
    ready, when the next one is due) and the reminder-delivery check, which is
    the one thing that distinguishes "the bot noticed the bump" from "the bot
    actually pinged somebody".
    """
    stats = stats_service.guild_bump_stats(config)
    now = int(stats["server_time"])

    ready = 0
    waiting = 0
    never = 0
    next_due: int | None = None
    last_bump: int | None = None
    reminders_pending = 0

    timestamps = config.timestamps or {}
    for bot in stats["bots"]:
        stamp = bot["last_bump"]
        if stamp is None:
            never += 1
        else:
            last_bump = stamp if last_bump is None else max(last_bump, stamp)
        if bot["status"] == "ready":
            ready += 1
        else:
            waiting += 1
            due = bot["next_due"]
            if due is not None:
                next_due = due if next_due is None else min(next_due, due)

        # A reminder is outstanding when the cooldown has elapsed and the stamp
        # recorded by the last delivered reminder is older than the bump it
        # should have covered. Never-bumped bots are excluded: there is nothing
        # for a reminder to have covered yet.
        reminded = int(timestamps.get(f"{bot['key']}_reminded", 0) or 0)
        if stamp is not None and bot["status"] == "ready" and reminded < stamp:
            reminders_pending += 1

        bot["reminded_for"] = reminded or None

    return {
        **stats,
        "ready_count": ready,
        "waiting_count": waiting,
        "never_bumped": never,
        "next_due": next_due,
        "last_bump": last_bump,
        "reminders_pending": reminders_pending,
        "now": now,
    }


# -- Setup health -----------------------------------------------------------


def build_setup(config: GuildConfig) -> dict:
    """``SetupOverview`` - what is configured, in the ids the dashboard speaks.

    Snowflakes leave as strings ("" when unset) exactly like
    ``routers/settings._serialize``, because they exceed JavaScript's safe
    integer range.
    """
    roles = config.roles or {}
    admin_role_ids = [str(r) for r in (roles.get("admin_role_ids") or [])]
    message = config.custom_message or ""

    return {
        "bump_channel": str(config.bump_channel) if config.bump_channel else "",
        "bump_role": str(config.bump_role) if config.bump_role else "",
        "timers_channel": str(config.timers_channel) if config.timers_channel else "",
        "timers_message": bool(config.timers_message),
        "custom_message_set": bool(message.strip()),
        "custom_message_length": len(message),
        "admin_role_count": len(admin_role_ids),
        "enabled_bots": [str(b) for b in (config.enabled_bots or [])],
        "supported_bots": [
            {"key": key, "name": BOT_DISPLAY_NAMES.get(key, key.title())}
            for key in SUPPORTED_BOTS
        ],
        "updated_at": _iso(config.updated_at),
        "created_at": _iso(config.created_at),
    }


# -- Change history ---------------------------------------------------------


def _audit_guild_filter(guild_id: int) -> dict:
    return {"guild_id": {"$in": _both_forms(guild_id)}}


def _entry_actor(doc: dict) -> str | None:
    """Best available name for whoever made the change.

    The admin seam stores the display name inside ``details.actor_name``; the
    retired premium cog stored no name at all (historical rows). A redacted entry keeps "[redacted]",
    which is a truthful answer and must survive to the page unchanged.
    """
    details = doc.get("details")
    if isinstance(details, dict):
        name = details.get("actor_name")
        if name:
            return str(name)
    name = doc.get("actor_name")
    return str(name) if name else None


def _entry_row(doc: dict) -> dict:
    """One audit entry as the overview's change row.

    Three writers, three shapes: the admin panel nests section/key inside
    ``details``, this dashboard writes them at the top level (the engine's
    canonical ``log_config_change`` shape), and the retired premium cog wrote a
    ``category`` (historical rows). All three are read here so a server's recent-changes list
    shows web edits and panel edits as the same kind of thing.
    """
    details = doc.get("details") if isinstance(doc.get("details"), dict) else {}
    action = str(doc.get("action") or "")
    return {
        "action": action,
        "section": str(
            details.get("section") or doc.get("section") or doc.get("category") or ""
        ),
        "key": str(details.get("key") or doc.get("key") or ""),
        "actor": _entry_actor(doc),
        "at": _iso(doc.get("created_at")),
    }


async def build_changes(guild_id: int) -> dict:
    """``ChangesOverview`` - the audit trail, the one real time series here.

    Every other number on this page is a snapshot of the current setup; the
    audit log is the only collection that accumulates rows over time, so it is
    the only thing a trend can honestly be drawn from.
    """
    audit = db_manager.get_collection_manager(_AUDIT_COLLECTION)
    guild_clause = _audit_guild_filter(guild_id)
    since = datetime.now(timezone.utc) - timedelta(days=TREND_DAYS)

    rows, recent, total = await asyncio.gather(
        audit.aggregate([
            {"$match": {**guild_clause, "created_at": {"$gte": since}}},
            {"$group": {
                "_id": {"$dateToString": {
                    "format": "%Y-%m-%d", "date": "$created_at", "timezone": "UTC",
                }},
                "count": {"$sum": 1},
            }},
        ]),
        audit.find_many(
            guild_clause,
            sort=[("created_at", -1)],
            limit=RECENT_CHANGES_LIMIT,
        ),
        audit.count_documents(guild_clause),
    )

    counts = {r["_id"]: int(r.get("count") or 0) for r in rows if r.get("_id")}
    daily = fill_daily(counts)

    return {
        "total": int(total),
        "total_30d": sum(counts.values()),
        "daily": daily,
        "recent": [_entry_row(doc) for doc in recent],
    }


# -- Feature status rail ----------------------------------------------------


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def build_features(
    config: GuildConfig,
    *,
    bumps: dict | None,
    setup: dict | None,
    changes: dict | None,
) -> list[dict]:
    """One ``FeatureStatus`` per feature, in the order the home page shows them.

    "needs_setup" is the state this rail exists for: switched on, looks alive,
    and missing the one value it cannot run without. A bump reminder that
    watches a channel it was never given, or pings a role that was never
    picked, reports itself perfectly healthy while doing nothing at all.
    """
    enabled_bots = [str(b) for b in (config.enabled_bots or [])]
    features: list[dict] = []

    # -- Bump watching -------------------------------------------------------
    if not enabled_bots:
        state, detail = "off", "No bump bots selected"
    elif not config.bump_channel:
        state, detail = "needs_setup", "No bump channel set"
    else:
        state = "on"
        last = (bumps or {}).get("last_bump")
        if isinstance(last, int):
            detail = f"Watching {_plural(len(enabled_bots), 'bump bot')}"
        else:
            detail = f"Watching {_plural(len(enabled_bots), 'bump bot')} - nothing seen yet"
    features.append({"key": "bumps", "label": "Bump watching", "state": state,
                     "detail": detail, "settings_key": "bumps"})

    # -- Reminder pings ------------------------------------------------------
    if not config.bump_role:
        state, detail = "needs_setup", "No reminder role set"
    elif not enabled_bots:
        state, detail = "off", "Nothing to remind about yet"
    else:
        state = "on"
        ready = (bumps or {}).get("ready_count")
        if isinstance(ready, int) and ready > 0:
            detail = f"{_plural(ready, 'bump')} ready now"
        elif isinstance(ready, int):
            detail = "Everything is on cooldown"
        else:
            detail = "Pinging your reminder role when a bump is due"
    features.append({"key": "reminders", "label": "Reminder pings", "state": state,
                     "detail": detail, "settings_key": "bumps"})

    # -- Live countdown ------------------------------------------------------
    if not config.timers_message:
        state, detail = "off", "Turned off"
    elif not config.timers_channel:
        state, detail = "needs_setup", "No timers channel set"
    else:
        state, detail = "on", "Keeping a countdown message up to date"
    features.append({"key": "timers", "label": "Live countdown", "state": state,
                     "detail": detail, "settings_key": "timers"})

    # -- Custom message ------------------------------------------------------
    has_message = bool((setup or {}).get("custom_message_set")) if setup is not None \
        else bool((config.custom_message or "").strip())
    if has_message:
        state, detail = "on", "Sending your own wording"
    else:
        state, detail = "off", "Sending the standard reminder"
    features.append({"key": "custom_message", "label": "Custom message", "state": state,
                     "detail": detail, "settings_key": "message"})

    # -- Who can manage ------------------------------------------------------
    # Never "off": Manage Server always opens this dashboard and the panel, so
    # reporting it as switched off would be a lie an admin could act on.
    role_count = (setup or {}).get("admin_role_count")
    if not isinstance(role_count, int):
        roles = config.roles or {}
        role_count = len(roles.get("admin_role_ids") or [])
    detail = (
        f"Manage Server, plus {_plural(role_count, 'role')}"
        if role_count else "Manage Server only"
    )
    features.append({"key": "access", "label": "Who can manage", "state": "on",
                     "detail": detail, "settings_key": "access"})

    # -- Change history ------------------------------------------------------
    # Content-only: there is no setting behind it, so it links nowhere.
    recent = (changes or {}).get("recent") or []
    if changes is None:
        state, detail = "off", "Not available"
    elif recent:
        state, detail = "on", f"{_plural(int(changes.get('total') or 0), 'change')} recorded"
    else:
        state, detail = "off", "Nothing changed yet"
    features.append({"key": "changes", "label": "Change history", "state": state,
                     "detail": detail, "settings_key": None})

    return features


def server_time() -> int:
    """Current unix time, so client countdowns can anchor to the server clock."""
    return int(time.time())
