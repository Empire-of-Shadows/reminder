from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from storage.config.guild_config_store import GuildConfigStore
from storage.log import get_logger

logger = get_logger("GuildConfig")

# Default cooldown Timers (in seconds)
THREE_0 = 30 * 60  # 30 minutes
ONE = 60 * 60      # 1 hour
TWO = 2 * 60 * 60  # 2 hours

def _default_roles() -> Dict[str, Any]:
    """Canonical panel-role config. Admin-only: there is no Mod tier."""
    return {"admin_role_ids": []}


def _normalize_roles(raw: Any) -> Dict[str, Any]:
    """Coerce a stored ``roles`` value into the canonical shape.

    Any other stored key (e.g. a pre-2026-08-06 ``mod_role_ids``) is dropped on
    read - the Mod tier is gone and nothing grants access from it.
    """
    raw = raw if isinstance(raw, dict) else {}
    return {"admin_role_ids": list(raw.get("admin_role_ids") or [])}



def _default_bot_delay() -> Dict[str, Any]:
    return {
        "bumpit": ONE,
        "bump4you": TWO,
        "disboard": TWO,
        "webump": TWO,
        "onebump": TWO,
        "unfocused": TWO,
    }

def _default_timestamps() -> Dict[str, Any]:
    return {
        "bumpit_timestamp": 0,
        "bump4you_timestamp": 0,
        "disboard_timestamp": 0,
        "webump_timestamp": 0,
        "onebump_timestamp": 0,
        "unfocused_timestamp": 0,
    }

DEFAULT_GUILD_CONFIG_DICT = {
    "enabled_bots": [],
    "bump_channel": 0,
    "bump_role": 0,
    "timers_channel": 0,
    "timers_message": True,
    "custom_message": "",
    "roles": _default_roles(),
    "bot_delay": _default_bot_delay(),
    "timestamps": _default_timestamps(),
}

@dataclass
class GuildConfig:
    """Represents configuration for a single guild in ImperialReminder."""
    guild_id: int
    enabled_bots: List[str] = field(default_factory=list)
    bump_channel: int = 0
    bump_role: int = 0
    timers_channel: int = 0
    timers_message: bool = True
    custom_message: str = ""
    # Canonical panel-role config (roles.admin_role_ids), consumed by the
    # dashboard and the admin panel to gate access.
    roles: Dict[str, Any] = field(default_factory=_default_roles)
    bot_delay: Dict[str, Any] = field(default_factory=_default_bot_delay)
    timestamps: Dict[str, Any] = field(default_factory=_default_timestamps)
    # Dynamic fields like timer_message_{channel_id} are handled in to_dict/from_dict
    extra_data: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        data = {
            "guild_id": str(self.guild_id),
            "enabled_bots": self.enabled_bots,
            "bump_channel": self.bump_channel,
            "bump_role": self.bump_role,
            "timers_channel": self.timers_channel,
            "timers_message": self.timers_message,
            "custom_message": self.custom_message,
            "roles": self.roles,
            "bot_delay": self.bot_delay,
            "timestamps": self.timestamps,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        # Merge extra_data (e.g. timer_message_{channel_id})
        data.update(self.extra_data)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GuildConfig":
        """Create from dictionary (database document)."""
        guild_id = int(data.get("guild_id") or data.get("_id") or 0)
        
        # Identify extra data (keys not in standard fields)
        standard_keys = {
            "guild_id", "_id", "enabled_bots", "bump_channel", "bump_role",
            # "premium" stays listed although the field is gone (2026-08-24, the
            # bot went 100% free): stored docs still carry the key until migration
            # m2 unsets it, and listing it here keeps it out of extra_data.
            "timers_channel", "timers_message", "custom_message", "roles", "premium",
            "bot_delay", "timestamps", "created_at", "updated_at"
        }
        extra_data = {k: v for k, v in data.items() if k not in standard_keys}

        return cls(
            guild_id=guild_id,
            enabled_bots=data.get("enabled_bots", []),
            bump_channel=data.get("bump_channel", 0),
            bump_role=data.get("bump_role", 0),
            timers_channel=data.get("timers_channel", 0),
            timers_message=data.get("timers_message", True),
            custom_message=data.get("custom_message", ""),
            roles=_normalize_roles(data.get("roles")),
            bot_delay=data.get("bot_delay", _default_bot_delay()),
            timestamps=data.get("timestamps", _default_timestamps()),
            extra_data=extra_data,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

class GuildConfigManager:
    """Typed wrapper over the engine GuildConfigStore.

    The store owns caching (hit-first via the CollectionManager's CacheBackend,
    30s TTL to bound cross-process staleness vs the dashboard) and every write is
    a surgical dotted ``$set`` - never a full-document replace. This class only
    adds the ``GuildConfig`` dataclass boundary and a last-read memo (``peek``)
    for synchronous display code.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._store: Optional[GuildConfigStore] = None
        self._last_read: Dict[int, GuildConfig] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the manager and connect the engine store to the collection."""
        if self._initialized:
            return
        try:
            self._store = GuildConfigStore(
                self.db_manager.get_collection_manager('settings_guild_data'),
                id_field="_id",
                cache_ttl=30,
            )
            self._initialized = True
            logger.info("GuildConfigManager initialized successfully (engine GuildConfigStore)")
        except Exception as e:
            logger.error(f"Failed to initialize GuildConfigManager: {e}", exc_info=True)
            raise

    async def get_config(self, guild_id: int, use_cache: bool = True) -> GuildConfig:
        """Get the configuration for a guild (default config if unconfigured)."""
        if not self._initialized:
            await self.initialize()

        try:
            doc = await self._store.get_doc(guild_id, use_cache=use_cache)
            if doc:
                config = GuildConfig.from_dict(doc)
            else:
                config = GuildConfig(guild_id=int(guild_id))
                logger.debug(f"Using default config for unconfigured guild {guild_id}")
        except Exception as e:
            logger.error(f"Error fetching config for guild {guild_id}: {e}", exc_info=True)
            return GuildConfig(guild_id=int(guild_id))

        self._last_read[int(guild_id)] = config
        return config

    def peek(self, guild_id: int) -> Optional[GuildConfig]:
        """Last GuildConfig read for this guild (sync, display-only; may be stale)."""
        return self._last_read.get(int(guild_id))

    def invalidate(self, guild_id: int) -> None:
        """Drop one guild's cached document and last-read memo."""
        if self._store is not None:
            self._store.invalidate(guild_id)
        self._last_read.pop(int(guild_id), None)

    async def save_config(self, config: GuildConfig) -> bool:
        """Persist a full config (dotted-$set upsert of its fields; timestamps engine-owned).

        Prefer set_value/set_values for partial edits - this writes every field the
        dataclass carries (it does not delete unknown stored fields).
        """
        if not self._initialized:
            await self.initialize()
        ok = await self._store.save_doc(config.guild_id, config.to_dict())
        if ok:
            self._last_read[int(config.guild_id)] = config
        return ok

    async def set_value(self, guild_id: int, key: str, value: Any) -> bool:
        """Set a specific (dotted) key for a guild via surgical $set."""
        if not self._initialized:
            await self.initialize()
        ok = await self._store.set_setting(key, value, guild_id)
        if ok:
            self._last_read.pop(int(guild_id), None)
        return ok

    async def set_values(self, guild_id: int, updates: Dict[str, Any]) -> bool:
        """Set several (dotted) keys for a guild in one surgical $set.

        Preferred over save_config for partial edits: it never rewrites the
        whole document, so concurrent writers (bot timestamps,
        dashboard) cannot clobber each other's fields.
        """
        if not updates:
            return True
        if not self._initialized:
            await self.initialize()
        ok = await self._store.set_many(updates, guild_id)
        if ok:
            self._last_read.pop(int(guild_id), None)
        return ok

_guild_config_manager: Optional[GuildConfigManager] = None

async def get_guild_config_manager(db_manager=None) -> GuildConfigManager:
    """Get or create the global GuildConfigManager instance."""
    global _guild_config_manager
    if _guild_config_manager is None:
        if db_manager is None:
            raise ValueError("db_manager is required for first initialization")
        _guild_config_manager = GuildConfigManager(db_manager)
        await _guild_config_manager.initialize()
    return _guild_config_manager
