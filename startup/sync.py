"""
Startup sync seam for ImperialReminder (bot-owned, NOT vendored).

The generic cog-loading machinery (discovery, priority/parallel loading, attribute
attachment, command-table logging) lives in the vendored runtime engine at
``startup/loader.py``. This file supplies only what is reminder-specific: the cog
discovery roots and ``attach_databases()`` (which managers exist and how they wire
onto the bot). ``Reminder.py`` keeps importing ``load_cogs`` / ``attach_databases`` /
``log_all_commands`` from here.
"""

from startup.bot import bot, s
from startup.loader import (  # noqa: F401 - log_all_commands is re-exported for Reminder.py
    attach_attribute,
    load_cogs as _engine_load_cogs,
    log_all_commands,
)
from storage.log import get_logger

logger = get_logger("Sync")


# Cog discovery roots. Priority cogs load first (sequential) for ordering-sensitive
# setup; the rest load in parallel for a faster boot.
COG_DIRECTORIES = ["./commands", "./admin", "./Features"]
PRIORITY_COG_DIRECTORIES: list[str] = []


async def load_cogs():
    """Load all cogs from the configured directories (engine loader)."""
    await _engine_load_cogs(bot, COG_DIRECTORIES, PRIORITY_COG_DIRECTORIES)


async def attach_databases():
    """
    Initialize the shared database manager and attach domain managers as bot
    attributes so cogs can read them via `bot.guild_config_manager` etc.
    """
    success_logs = [f"{s}🔄 Starting database attachment process...\n"]
    failed_logs = []

    try:
        # Initialize the shared DatabaseManager (pooled pymongo connections)
        from storage.settings.collections import db_manager
        try:
            await db_manager.initialize()
            result, is_success = await attach_attribute(bot, "db_manager", db_manager)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as db_error:
            failed_logs.append(f"{s}❌ db_manager → Error: {db_error}\n")
            raise  # Can't continue without db_manager

        # Audit log - engine AuditLog service over the registered TTL'd collection.
        from storage.audit_log import get_audit_log_manager
        try:
            audit_log_manager = get_audit_log_manager(db_manager)
            result, is_success = await attach_attribute(bot, "audit_log", audit_log_manager)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as audit_error:
            failed_logs.append(f"{s}❌ audit_log → Error: {audit_error}\n")

        # Unified GuildConfigManager (typed wrapper over the engine GuildConfigStore)
        try:
            from storage.config_manager import get_guild_config_manager
            guild_config_manager = await get_guild_config_manager(db_manager)
            result, is_success = await attach_attribute(bot, "guild_config_manager", guild_config_manager)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as config_error:
            failed_logs.append(f"{s}❌ guild_config_manager → Error: {config_error}\n")

        # Setup gatekeeper (engine SetupGate over the config manager)
        try:
            from storage.setup_gatekeeper import setup_gatekeeper
            setup_gatekeeper.set_config_manager(guild_config_manager)
            result, is_success = await attach_attribute(bot, "setup_gatekeeper", setup_gatekeeper)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as gate_error:
            failed_logs.append(f"{s}❌ setup_gatekeeper → Error: {gate_error}\n")

        # Timer handler - SINGLETON: exactly one instance, created here. Never
        # instantiate another (duplication breaks cancellation and remaining-time math).
        from Features.time_handler import TimerHandler
        try:
            timer_handler = TimerHandler(bot)
            result, is_success = await attach_attribute(bot, "timer_handler", timer_handler)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as timer_error:
            failed_logs.append(f"{s}❌ timer_handler → Error: {timer_error}\n")

        # IdleManager - rotating presence (rotation started in on_ready)
        from Features.idle import IdleManager
        try:
            idle_manager = IdleManager(bot)
            result, is_success = await attach_attribute(bot, "idle_manager", idle_manager)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as idle_error:
            failed_logs.append(f"{s}❌ idle_manager → Error: {idle_error}\n")
    except Exception as e:
        failed_logs.append(f"{s}❌ Encountered a critical error during database attachment → {e}\n")

    if failed_logs:
        failed_logs.insert(0, f"{s}❌ Failed to attach the following attributes:\n")
    if success_logs:
        success_logs.insert(1 if failed_logs else 0, f"{s}✅ Successfully attached the following attributes:\n")

    final_log = failed_logs + success_logs
    logger.info("\n" + "".join(final_log) + f"{s}✅ Database attachment process completed.\n")
