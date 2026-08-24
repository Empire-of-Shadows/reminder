"""Audit-log read API - admin only.

The ``audit_log`` collection is the one place in this bot that accumulates rows
over time, and it is written by three different code paths with three different
shapes:

* the admin panel seam (``admin/settings/bindings.audit_log_entry``) writes
  ``user_id`` as an INT, ``action`` as ``"set:section.key"``, and puts the
  actor name, section, key and before/after inside ``details``;
* this dashboard (``routers/settings``) writes the engine's canonical
  ``log_config_change`` shape - ``actor_id``/``section``/``key``/``old_value``/
  ``new_value`` at the top level, with ``source: "dashboard"``;
* the retired premium cog (removed 2026-08-24) wrote ``category: "premium"``
  with a ``payload`` - its historical rows still render.

``_row`` folds all three into one table row rather than showing an admin three
different-looking histories of their own server. An entry whose shape is not
recognised still renders - the raw action is more use than a dropped row.

Both guild-id spellings are matched (the panel writes int, this dashboard and the
retired premium cog's historical rows write str), the same way ``services/overview.py`` does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.auth.panel_role import require_panel_access, resolve_panel_role
from storage.settings.collections import db_manager
from storage.log import get_logger

logger = get_logger("dashboard.routers.audit_log")

router = APIRouter(tags=["audit-log"])

_AUDIT_COLLECTION = "audit_log"
#: Window the summary tile reports on, matching the overview's change trend.
SUMMARY_DAYS = 30


def _both_forms(value: Any) -> list[Any]:
    """The int and str spellings of a snowflake, for filters that must match both."""
    forms: list[Any] = [str(value)]
    try:
        forms.append(int(value))
    except (TypeError, ValueError):
        pass
    return forms


def _iso(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _actor_name(doc: dict, details: dict) -> str | None:
    """Best available name for whoever made the change.

    A redacted entry carries "[redacted]", which is a truthful answer and must
    reach the page unchanged rather than being turned back into an id.
    """
    for candidate in (details.get("actor_name"), doc.get("actor_name")):
        if candidate:
            return str(candidate)
    return None


def _actor_id(doc: dict) -> str | None:
    for candidate in (doc.get("actor_id"), doc.get("user_id")):
        if candidate is not None:
            return str(candidate)
    return None


def _row(doc: dict) -> dict:
    """One audit entry, folded into the table's single shape."""
    details = doc.get("details") if isinstance(doc.get("details"), dict) else {}
    payload = doc.get("payload") if isinstance(doc.get("payload"), dict) else None
    action = str(doc.get("action") or "")

    section = str(details.get("section") or doc.get("section") or doc.get("category") or "")
    key = str(details.get("key") or doc.get("key") or "")
    # The panel's action is "set:section.key"; the bare verb reads better in a
    # column that already has its own section and key columns.
    verb = action.split(":", 1)[0] if ":" in action else action
    if not key and ":" in action:
        key = action.split(":", 1)[1]

    old_value = details.get("old_value", doc.get("old_value"))
    new_value = details.get("new_value", doc.get("new_value"))
    if new_value is None and payload is not None:
        # Premium grants/revokes carry their detail in `payload` instead.
        new_value = payload

    return {
        "at": _iso(doc.get("created_at")),
        "actor": _actor_name(doc, details),
        "actor_id": _actor_id(doc),
        "source": str(doc.get("source") or ("panel" if "user_id" in doc else "bot")),
        "section": section,
        "key": key,
        "action": verb or action,
        "old_value": old_value,
        "new_value": new_value,
        "redacted": doc.get("redacted_at") is not None,
    }


@router.get("/guilds/{guild_id}/audit-log")
async def guild_audit_log(
    guild_id: int,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None, description="ISO timestamp cursor"),
    session: dict = Depends(require_panel_access),
):
    """One page of a server's change history, newest first.

    Cursor pagination on ``created_at`` rather than skip/limit: entries are only
    ever appended and the TTL only ever drops the oldest, so a cursor cannot
    skip or repeat a row the way an offset can while the page is open.

    ``summary`` is returned on the first page only (there is no cursor), because
    that is the only request where a total is worth the extra count.
    """
    role = await resolve_panel_role(session, str(guild_id))
    # require_panel_access already rejects "none"; this is defense in depth
    # against a future tier ever being added, matching routers/settings.
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    query: dict = {"guild_id": {"$in": _both_forms(guild_id)}}
    if before:
        try:
            cursor_at = datetime.fromisoformat(before)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'before' timestamp")
        query["created_at"] = {"$lt": cursor_at}

    audit = db_manager.get_collection_manager(_AUDIT_COLLECTION)
    # One extra row answers "is there another page" without a second count.
    docs = await audit.find_many(query, sort=[("created_at", -1)], limit=limit + 1)

    has_more = len(docs) > limit
    docs = docs[:limit]
    next_cursor = None
    if has_more and docs:
        next_cursor = _iso(docs[-1].get("created_at"))

    payload: dict[str, Any] = {
        "entries": [_row(doc) for doc in docs],
        "next_cursor": next_cursor,
    }

    if before is None:
        guild_clause = {"guild_id": {"$in": _both_forms(guild_id)}}
        since = datetime.now(timezone.utc) - timedelta(days=SUMMARY_DAYS)
        try:
            total = await audit.count_documents(guild_clause)
            recent = await audit.count_documents(
                {**guild_clause, "created_at": {"$gte": since}}
            )
            payload["summary"] = {
                "total": int(total),
                "window_days": SUMMARY_DAYS,
                "total_window": int(recent),
                "newest": payload["entries"][0]["at"] if payload["entries"] else None,
            }
        except Exception:
            # A failed count must not cost the admin the entries themselves, and
            # it must not be dressed up as "0 changes recorded" either.
            logger.warning("audit summary failed for guild %s", guild_id, exc_info=True)
            payload["summary"] = None

    return payload
