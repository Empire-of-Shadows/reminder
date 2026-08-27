"""
Admin Panel Config Trees for ImperialReminder.

Defines the PanelNode config tree for the bump-reminder admin panel. The shared
engine (admin_cog + views/panel_engine) consumes this tree; only get/set/clear
accessor helpers and the tree shape are bot-specific.

Accessor contract (per PanelNode):
    get_values:   async (guild_id) -> list
    set_values:   async (guild_id, values) -> bool
    clear_values: async (guild_id) -> bool

Top-level shape follows ADMIN_PANEL_STANDARD.md 1.1 (menu when an entry groups two
or more settings, leaf when it is a single setting): Core Setup and Panel Access
Roles form the "main" cluster, with Bump Bots / Messages below the
"Feature Configurations" divider. There is no Premium section: the bot is
100% free (premium removed 2026-08-24).

The panel is admin-only: ``bindings.resolve_panel_role`` never returns "mod", so no
the engine's ``mod_allowed`` node flag was removed fleet-wide on 2026-08-06.
"""

import discord

from .panel_branding import PANEL_DESCRIPTION, PANEL_TITLE
from ..views.panel_engine import PanelNode
from ..actions.features import panel_roles_pair
from storage.config_manager import get_guild_config_manager
from storage.sub_systems.bump_config import (
    BUMP_BOTS,
    BUMP_BOTS_CHOICES,
    SUPPORTED_BOTS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Channel / role accessors
# ─────────────────────────────────────────────────────────────────────────────

async def _get_channel(guild_id: int, attr: str) -> list:
    cm = await get_guild_config_manager()
    config = await cm.get_config(guild_id)
    val = getattr(config, attr, 0)
    return [val] if val else []


async def _set_channel(guild_id: int, values: list, attr: str) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(guild_id, attr, int(values[0]) if values else 0)


async def _clear_channel(guild_id: int, attr: str) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(guild_id, attr, 0)


async def _post_save_bump_channel(interaction, guild_id: int, values: list) -> None:
    """Default the timers channel to the bump channel when unset (mirrors old /bump setup)."""
    if not values:
        return
    cm = await get_guild_config_manager()
    config = await cm.get_config(guild_id)
    if not config.timers_channel:
        await cm.set_value(guild_id, "timers_channel", int(values[0]))


async def _get_role(guild_id: int) -> list:
    cm = await get_guild_config_manager()
    config = await cm.get_config(guild_id)
    return [config.bump_role] if config.bump_role else []


async def _set_role(guild_id: int, values: list) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(guild_id, "bump_role", int(values[0]) if values else 0)


async def _clear_role(guild_id: int) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(guild_id, "bump_role", 0)


async def _bump_role_validator(guild, values) -> str | None:
    """Refuse a bump role that could never actually ping anybody.

    Bot policy, not engine policy: the reminder renders `<@&id>` and sends it
    with a per-send AllowedMentions that allows only the configured role
    (handler.py `_delayed_send`). Discord then delivers no ping at all - while
    the text still renders - when the role is @everyone (stripped by
    `everyone=False`), integration-managed, not mentionable, or gone. Every one
    of those saves cleanly and then reminds nobody, with no error anywhere, so
    the pick is refused at save time instead.

    Hierarchy is deliberately NOT checked (see the node comment): the bot only
    mentions this role, it never assigns it.

    Engine contract (admin_cog select save): async (guild, values) -> an error
    string to refuse with, or None when every value is acceptable.
    """
    for rid in values:
        role = guild.get_role(int(rid))
        if role is None:
            return "Could not find that role. It may have been deleted."

        if role.is_default():
            return (
                "**@everyone** cannot be used as the bump role - the reminder "
                "would print the mention as plain text and ping nobody.\n\n"
                "Pick a normal, mentionable role instead."
            )

        if role.managed:
            return (
                f"**@{role.name}** is managed by an integration (a bot role, the "
                f"Server Booster role, or a subscription role). Discord does not "
                f"let it be made mentionable, so the reminder would ping "
                f"nobody.\n\nPick a normal, mentionable role instead."
            )

        if not role.mentionable:
            return (
                f"**@{role.name}** is not mentionable, so the reminder would "
                f"print the role name as plain text and ping nobody.\n\n"
                f"Turn on **Allow anyone to @mention this role** in Server "
                f"Settings > Roles > @{role.name}, or pick a role that already "
                f"has that turned on."
            )

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Bump bots accessors
# ─────────────────────────────────────────────────────────────────────────────

async def _get_enabled_bots(guild_id: int) -> list:
    cm = await get_guild_config_manager()
    config = await cm.get_config(guild_id)
    return [str(b) for b in (config.enabled_bots or [])]


async def _set_enabled_bots(guild_id: int, values: list) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(guild_id, "enabled_bots", [str(v) for v in values])


async def _get_delay(guild_id: int, bot_name: str) -> list:
    cm = await get_guild_config_manager()
    config = await cm.get_config(guild_id)
    val = config.bot_delay.get(bot_name, BUMP_BOTS.get(bot_name))
    return [str(val)] if val is not None else []


async def _set_delay(guild_id: int, values: list, bot_name: str) -> bool:
    if not values:
        return False
    cm = await get_guild_config_manager()
    return await cm.set_value(guild_id, f"bot_delay.{bot_name}", int(values[0]))


# ─────────────────────────────────────────────────────────────────────────────
# Messages accessors
# ─────────────────────────────────────────────────────────────────────────────

async def _get_custom_message(guild_id: int) -> list:
    cm = await get_guild_config_manager()
    config = await cm.get_config(guild_id)
    return [config.custom_message] if config.custom_message else []


async def _set_custom_message(guild_id: int, values: list) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(guild_id, "custom_message", values[0] if values else "")


async def _clear_custom_message(guild_id: int) -> bool:
    cm = await get_guild_config_manager()
    return await cm.set_value(guild_id, "custom_message", "")


async def _get_timers_message(guild_id: int) -> list:
    cm = await get_guild_config_manager()
    config = await cm.get_config(guild_id)
    return ["on"] if config.timers_message else ["off"]


async def _set_timers_message(guild_id: int, values: list) -> bool:
    cm = await get_guild_config_manager()
    enabled = (values[0] == "on") if values else True
    return await cm.set_value(guild_id, "timers_message", enabled)




# ─────────────────────────────────────────────────────────────────────────────
# Lock computation
# ─────────────────────────────────────────────────────────────────────────────

async def _main_locked_children(guild_id: int) -> set[str]:
    """Lock Bump Bots / Messages until a bump channel and role are set."""
    cm = await get_guild_config_manager()
    config = await cm.get_config(guild_id)
    if not (config.bump_channel and config.bump_role):
        return {"bots", "messages"}
    return set()


# ─────────────────────────────────────────────────────────────────────────────
# Core Setup
# ─────────────────────────────────────────────────────────────────────────────

SETUP_CONFIG = PanelNode(
    key="setup",
    label="Core Setup",
    kind="menu",
    category_group="main",
    description=(
        "The minimum configuration. A **Bump Channel** and **Bump Role** are "
        "required before reminders run."
    ),
    children={
        "bump_channel": PanelNode(
            key="bump_channel",
            label="Bump Channel",
            kind="channel_select",
            description="Channel your bump bots post in - reminders are sent here.",
            get_values=lambda gid: _get_channel(gid, "bump_channel"),
            set_values=lambda gid, vals: _set_channel(gid, vals, "bump_channel"),
            clear_values=lambda gid: _clear_channel(gid, "bump_channel"),
            post_save_hook=_post_save_bump_channel,
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            # The bot's full working set in this channel: it reads bump-bot posts
            # (view), sends reminders (send - plain content only, no embed), and
            # refetches messages for WeBump's delayed edit and the empty-payload
            # fallback (read_message_history - handler.py on_message_edit/refetch).
            # embed_links is here for the countdown TIMER embed, not the reminder:
            # when timers_channel is unset (0) the embed falls back into this
            # channel (embed_manager._resolve_timer_channel, sent in
            # _delayed_update). Both refetch sites are try/except-wrapped, so a
            # missing History perm would weaken detection SILENTLY - refuse it at
            # save time instead.
            required_channel_perms=[
                "view_channel",
                "send_messages",
                "embed_links",
                "read_message_history",
            ],
        ),
        # Deliberately NO requires_role_manage on bump_role: the bot only MENTIONS
        # this role in reminders - it never assigns or edits it - and the hierarchy
        # rule would wrongly reject above-bot roles an admin may want pinged. What
        # the pick does have to be is PINGABLE, which is what the value_validator
        # guards instead (_bump_role_validator).
        "bump_role": PanelNode(
            key="bump_role",
            label="Bump Role",
            kind="role_select",
            description="Role mentioned when it's time to bump again.",
            get_values=_get_role,
            set_values=_set_role,
            clear_values=_clear_role,
            value_validator=_bump_role_validator,
            min_values=1,
            max_values=1,
        ),
        "timers_channel": PanelNode(
            key="timers_channel",
            label="Timers Channel",
            kind="channel_select",
            description=(
                "Channel where the live countdown timer embed is shown. "
                "Defaults to the Bump Channel."
            ),
            get_values=lambda gid: _get_channel(gid, "timers_channel"),
            set_values=lambda gid, vals: _set_channel(gid, vals, "timers_channel"),
            clear_values=lambda gid: _clear_channel(gid, "timers_channel"),
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            # Countdown embed lifecycle: send the new embed (send + embed) and
            # fetch-then-delete the previous one (read_message_history -
            # embed_manager._delayed_update). Without History the old embed cannot
            # be fetched, so stale countdowns pile up with only a warning log -
            # refuse the channel at save time instead.
            required_channel_perms=[
                "view_channel",
                "send_messages",
                "embed_links",
                "read_message_history",
            ],
        ),
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# Bump Bots
# ─────────────────────────────────────────────────────────────────────────────

def _bot_label(bot_name: str) -> str:
    return bot_name.capitalize()


def _build_cooldown_children() -> dict:
    """Build one option_select node per supported bot for the Cooldowns submenu."""
    children: dict[str, PanelNode] = {}
    for bot_name in SUPPORTED_BOTS:
        choices = BUMP_BOTS_CHOICES.get(bot_name, {f"{BUMP_BOTS[bot_name] // 60} Minutes": BUMP_BOTS[bot_name]})
        options = [(str(secs), label) for label, secs in choices.items()]
        children[f"cd_{bot_name}"] = PanelNode(
            key=f"cd_{bot_name}",
            label=_bot_label(bot_name),
            kind="option_select",
            description=f"Reminder cooldown for {_bot_label(bot_name)}.",
            options=options,
            get_values=lambda gid, b=bot_name: _get_delay(gid, b),
            set_values=lambda gid, vals, b=bot_name: _set_delay(gid, vals, b),
            min_values=1,
            max_values=1,
        )
    return children


BOTS_CONFIG = PanelNode(
    key="bots",
    label="Bump Bots",
    kind="menu",
    category_group="feature",
    description="Choose which bump bots to track and tune each one's reminder cooldown.",
    children={
        "enabled_bots": PanelNode(
            key="enabled_bots",
            label="Enabled Bots",
            kind="option_select",
            description="Pick which bump bots Imperial Reminder should watch.",
            options=[(b, _bot_label(b)) for b in SUPPORTED_BOTS],
            get_values=_get_enabled_bots,
            set_values=_set_enabled_bots,
            min_values=0,
            max_values=len(SUPPORTED_BOTS),
        ),
        "cooldowns": PanelNode(
            key="cooldowns",
            label="Cooldowns",
            kind="menu",
            description="Per-bot reminder cooldowns.",
            children=_build_cooldown_children(),
        ),
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────────────

MESSAGES_CONFIG = PanelNode(
    key="messages",
    label="Messages",
    kind="menu",
    category_group="feature",
    description="Customize reminder text and the live timer embed.",
    children={
        "custom_message": PanelNode(
            key="custom_message",
            label="Custom Reminder Message",
            kind="modal_input",
            description=(
                "Optional message appended to reminders. Placeholders: "
                "`{bump_role}` (the role mention) and `{bots}` (the bots due). "
                "Leave empty to clear."
            ),
            modal_title="Custom Reminder Message",
            modal_label="Message",
            modal_placeholder="Time to bump! {bump_role}",
            modal_min_length=0,
            modal_max_length=500,
            modal_paragraph=True,
            modal_required=False,
            get_values=_get_custom_message,
            set_values=_set_custom_message,
            clear_values=_clear_custom_message,
        ),
        "timers_message": PanelNode(
            key="timers_message",
            label="Show Timer Embed",
            kind="option_select",
            description="Whether to display the live countdown timer embed.",
            options=[("on", "On (Default)"), ("off", "Off")],
            get_values=_get_timers_message,
            set_values=_set_timers_message,
            min_values=1,
            max_values=1,
        ),
    },
)




# ─────────────────────────────────────────────────────────────────────────────
# Panel Access Roles (engine panel_roles_pair over roles.admin_role_ids)
# ─────────────────────────────────────────────────────────────────────────────

# One setting, so it is a top-level LEAF, not a single-child wrapper menu
# (ADMIN_PANEL_STANDARD.md 1.1). The panel and the dashboard are admin-only, there
# is no Mod tier. str_ids=True: the dashboard already stores
# roles.admin_role_ids as string snowflakes; keep one storage convention.
# Changing panel access requires Manage Server (the builder's default pre_check is
# the engine manage_guild_pre_check), so a delegated admin cannot widen access.
ACCESS_ROLES_CONFIG = panel_roles_pair(
    admin_key="panel_access_roles",
    admin_description=(
        "Roles that may open `/admin panel` and the dashboard; Manage Server "
        "always has access."
    ),
    str_ids=True,
)["panel_access_roles"]
ACCESS_ROLES_CONFIG.category_group = "main"


# ─────────────────────────────────────────────────────────────────────────────
# Top-level panel tree
# ─────────────────────────────────────────────────────────────────────────────

MAIN_PANEL = PanelNode(
    key="main",
    label=PANEL_TITLE,
    kind="menu",
    description=PANEL_DESCRIPTION,
    locked_children=_main_locked_children,
    lock_reason=(
        "Finish **Core Setup** first - set a **Bump Channel** and **Bump Role**, "
        "then this section unlocks."
    ),
    children={
        # ── Main Configurations ───────────────────────────────────────
        "setup": SETUP_CONFIG,
        "panel_access_roles": ACCESS_ROLES_CONFIG,

        # ── Feature Configurations ────────────────────────────────────
        "bots": BOTS_CONFIG,
        "messages": MESSAGES_CONFIG,
    },
)
