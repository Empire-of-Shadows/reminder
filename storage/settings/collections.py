"""storage_engine - collection registry + manager for ImperialReminder (bot-owned, NOT vendored).

This one file declares ImperialReminder's collections AND constructs the shared
``db_manager`` the rest of the bot imports (``from storage.settings.collections import
db_manager``). It replaces the old ``define_collections`` + ``database_properties`` +
``manager`` trio: the engine base builds its own per-collection accessor map
(``db_manager.<registry_key>``) from the registry at construction, so attribute
accessors like ``db_manager.settings_guild_data`` keep working with no properties
file.

Index shapes are carried over from the old ``define_collections.py`` and database names
are preserved, so current data (live guild settings, bump timestamps) is reused with no
migration.

ENGINE CONTRACT: the registry is a ``dict[str, CollectionConfig]`` passed as
``collection_configs=``. The dict key is the *registry key* passed to
``db_manager.get_collection_manager(key)`` and listed in ``bindings.WATCHED_COLLECTIONS``.

Template: ``EmpireSystems/Settings/storage/collections_reference.py``.
"""

from __future__ import annotations

from pymongo import IndexModel

from storage.core.collection_config import CollectionConfig
from storage.database_manager import DatabaseManagerBase
from . import bindings

# Existing database name - preserved so current data is reused (no migration).
REMINDER_DB = "ImperialReminder"


# -- ImperialReminder's collections (registry_key -> CollectionConfig) -----------
COLLECTIONS: dict[str, CollectionConfig] = {
    # Per-guild settings + bump timestamps (LIVE production data - never dropped).
    "settings_guild_data": CollectionConfig(
        name="GuildData",
        database=REMINDER_DB,
        connection="primary",
        # No declared indexes: the old premium_enabled_idx is dropped by
        # migration m2 (premium removed 2026-08-24, the bot is 100% free).
        indexes=[],
    ),
    # Admin-panel audit trail (written by the engine AuditLog service via
    # storage/audit_log.py). Collection name matches the old hand-rolled writer so
    # existing entries stay put; retention applies to new engine-written entries
    # (TTL on ``created_at``).
    "audit_log": CollectionConfig(
        name="audit_log",
        database=REMINDER_DB,
        connection="primary",
        indexes=[
            IndexModel([("guild_id", 1)], name="audit_guild_id_idx"),
            IndexModel([("created_at", 1)], name="audit_ttl",
                       expireAfterSeconds=31_536_000),  # 365 days
        ],
    ),
}


class DatabaseManager(DatabaseManagerBase):
    """ImperialReminder's MongoDB manager (engine core; no bot-specific extensions since
    the premium subsystem was removed 2026-08-24 - the raw get_collection/db_client
    accessors existed only for the engine PremiumManager to bind through)."""



# -- The shared manager (constructed from bindings + the registry above) ---------
db_manager = DatabaseManager(
    primary_uri=bindings.MONGO_URIS["primary"],
    cache=bindings.build_cache(),
    watched_collections=bindings.WATCHED_COLLECTIONS,
    collection_configs=COLLECTIONS,
)
# At startup: ``await db_manager.initialize()``; at shutdown: ``await db_manager.close()``.
