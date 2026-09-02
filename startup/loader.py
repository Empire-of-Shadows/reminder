# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""Cog discovery/loading + command-table logging (engine-owned).

The generic startup machinery every EoS bot shares: walk the cog directories, load
priority cogs sequentially then the rest in parallel, attach attributes onto the bot,
and log the registered command tables (global AND guild-scoped) at boot.

The bot-owned ``startup/sync.py`` seam supplies everything bot-specific - the ``bot``
instance, ``COG_DIRECTORIES`` / ``PRIORITY_COG_DIRECTORIES``, and ``attach_databases()`` -
and calls into these functions::

    from startup.loader import load_cogs as engine_load_cogs, log_all_commands

    COG_DIRECTORIES = ["./commands", "./admin", "./Features"]
    PRIORITY_COG_DIRECTORIES: list[str] = []

    async def load_cogs():
        await engine_load_cogs(bot, COG_DIRECTORIES, PRIORITY_COG_DIRECTORIES)

Every function takes the bot explicitly so this file stays bot-agnostic.
"""

import asyncio
import os
from pathlib import Path

import discord
from tabulate import tabulate

from storage.log import get_logger, log_performance

logger = get_logger("Sync")

# Log indent used by the startup summaries (mirrors the bots' `s` constant).
s = " " * 10


def generate_cog_module_name(root, file):
    """Generate the fully qualified module name from root and file."""
    relative_path = os.path.relpath(os.path.join(root, file), start=str(Path("."))).replace("\\", "/")
    module_name = relative_path.replace("/", ".").removesuffix(".py")
    logger.debug(f"Generating module name for {file}: {module_name}")
    return module_name


def discover_cog_modules(bot, directories: list[str]) -> list[tuple[str, str]]:
    """
    Walk directories and return a list of (module_name, file_path) tuples.
    Does not load anything - just discovers (skips already-loaded modules).
    """
    cogs = []
    for base_dir in directories:
        if not os.path.exists(base_dir):
            logger.debug(f"Directory does not exist, skipping: {base_dir}")
            continue
        for root, _, files in os.walk(base_dir):
            for file in files:
                if not file.endswith(".py") or file.startswith("__"):
                    continue
                module_name = generate_cog_module_name(root, file)
                if module_name not in bot.extensions:
                    cogs.append((module_name, os.path.join(root, file)))
    return cogs


async def safely_load_cog(bot, module, file_path):
    """
    Dynamically import and load a cog module.
    Returns a formatted log line and a success flag. Skips files without setup().
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "\ndef setup(" not in content and "\nasync def setup(" not in content:
            logger.debug(f"Skipping {module} - no setup() function")
            return None, None
    except Exception:
        pass  # File unreadable; let load_extension surface the real error

    try:
        await bot.load_extension(module)
        return f"{s}  {module}\n", True
    except Exception as e:
        return f"{s}  FAILED {module} -> Error: {e}\n", False


@log_performance("load_cogs")
async def load_cogs(bot, cog_directories: list[str],
                    priority_cog_directories: list[str] | None = None):
    """
    Load all cogs from the given directories. Priority cogs (ordering-sensitive)
    load first sequentially; the remaining cogs load in parallel for a faster boot.
    """
    success_logs = [f"{s}Starting cog loading process...\n"]
    failed_logs = []

    # Phase 1: discover all cogs
    priority_cogs = discover_cog_modules(bot, priority_cog_directories or [])
    regular_cogs = discover_cog_modules(bot, cog_directories)

    # Filter priority cogs out of the regular set (avoid double-loading)
    priority_modules = {mod for mod, _ in priority_cogs}
    regular_cogs = [(mod, path) for mod, path in regular_cogs if mod not in priority_modules]

    logger.debug(f"Discovered {len(priority_cogs)} priority cogs, {len(regular_cogs)} regular cogs")

    # Phase 2: load priority cogs first (sequential - ordering matters)
    if priority_cogs:
        success_logs.append(f"{s}Loading priority cogs (sequential)...\n")
        for module_name, file_path in priority_cogs:
            result, is_success = await safely_load_cog(bot, module_name, file_path)
            if result is None:
                continue
            if is_success:
                success_logs.append(result)
            else:
                failed_logs.append(result)

    # Phase 3: load remaining cogs in parallel
    if regular_cogs:
        success_logs.append(f"{s}Loading remaining cogs (parallel)...\n")
        results = await asyncio.gather(
            *[safely_load_cog(bot, mod, path) for mod, path in regular_cogs],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                failed_logs.append(f"{s}Unexpected error: {result}\n")
            else:
                log_msg, is_success = result
                if log_msg is None:
                    continue
                if is_success:
                    success_logs.append(log_msg)
                else:
                    failed_logs.append(log_msg)

    # Summary
    if failed_logs:
        failed_logs.insert(0, f"{s}Failed to load the following cogs:\n")
    success_logs.append(f"{s}Successfully loaded cogs:\n")

    # Failures get their own ERROR record, never a line inside the INFO blob.
    # Learned 2026-08-28: an admin-cog load failure shipped inside the INFO
    # summary and was missed on the production host - the bot ran with no
    # admin panel and nothing at ERROR level said so.
    if failed_logs:
        logger.error("\n" + "".join(failed_logs))
    logger.info("\n" + "".join(success_logs) + f"{s}Cog loading process completed.\n")


async def attach_attribute(bot, attribute_name, attribute_value):
    """Safely attach an attribute to the bot and return its status."""
    try:
        setattr(bot, attribute_name, attribute_value)
        return f"{s}✅ {attribute_name}: {attribute_value}\n", True
    except Exception as e:
        return f"{s}❌ {attribute_name} → Error: {e}\n", False


async def log_all_commands(bot) -> None:
    """
    Log all registered prefix and slash commands in tabular form.

    Slash commands are rendered as a tree: each group lists its subcommands
    indented beneath it, with descriptions. Guild-scoped commands (which live in a
    separate part of the tree and never appear in the global list) get their own
    table per guild.
    """
    prefix_commands = [
        [cmd.name, cmd.help or "No description provided", ", ".join(cmd.aliases) or "None"]
        for cmd in bot.commands
    ]

    if prefix_commands:
        prefix_table = tabulate(
            prefix_commands,
            headers=["Prefix Command", "Description", "Aliases"],
            tablefmt="fancy_grid",
        )
        logger.info(f"📝 Registered Prefix Commands ({len(prefix_commands)}):\n{prefix_table}")
    else:
        logger.info("📝 No prefix commands registered")

    def build_rows(commands_iter):
        """Flatten a command iterable into tree rows + a leaf (invocable) count."""
        rows: list[list[str]] = []
        leaves = 0

        def add_command(cmd, depth: int = 0):
            nonlocal leaves
            label = ("  " * depth + "↳ " if depth else "") + cmd.name
            description = getattr(cmd, "description", None) or "No description provided"
            if isinstance(cmd, discord.app_commands.Group):
                rows.append([label, description, "Group"])
                for sub in cmd.commands:
                    add_command(sub, depth + 1)
            else:
                leaves += 1
                rows.append([label, description, "Subcmd" if depth else "Slash"])

        for cmd in commands_iter:
            add_command(cmd)
        return rows, leaves

    # Global commands (synced to every guild).
    global_rows, global_leaves = build_rows(bot.tree.get_commands())
    if global_rows:
        table = tabulate(global_rows, headers=["Command", "Description", "Type"], tablefmt="fancy_grid")
        logger.info(f"⚡ Registered Global Slash Commands ({global_leaves}):\n{table}")
    else:
        logger.info("⚡ No global slash commands registered")

    # Guild-scoped commands (e.g. an owner-only admin group). Enumerate every guild the
    # tree has commands registered for and log each one.
    guild_ids = sorted(getattr(bot.tree, "_guild_commands", {}).keys())
    for gid in guild_ids:
        rows, leaves = build_rows(bot.tree.get_commands(guild=discord.Object(id=gid)))
        if not rows:
            continue
        guild = bot.get_guild(gid)
        in_guild = "" if guild else "  [bot NOT in this guild - guild sync will fail]"
        gname = f"{guild.name} ({gid})" if guild else str(gid)
        table = tabulate(rows, headers=["Command", "Description", "Type"], tablefmt="fancy_grid")
        logger.info(f"⚡ Registered Guild Slash Commands for {gname} ({leaves}):{in_guild}\n{table}")
