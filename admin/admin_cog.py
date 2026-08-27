# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""
Admin Commands Cog - Multi-Message Config Panel

Main cog with /admin panel command using Discord Components v2 LayoutViews.
Uses the PanelNode engine for all navigation -no per-feature view builders needed.

Message pattern:
  Message 1 (Overview):  Persistent full-detail server config overview. Always visible,
                          updates in-place when settings change.
  Message 2 (Settings):  Sent as followup when a category is selected. All navigation
                          and setting changes happen here. Auto-closed on new selection.
  Message 3 (Notices):   Ephemeral followup for errors, locks, permission failures.
"""

import json
import time
import uuid
import logging
from collections.abc import Awaitable, Callable
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# All bot-specific backends (config, audit, premium, cache invalidation, panel-role
# resolution, branding text) are reached through this per-bot seam, so this engine file
# stays byte-identical across every bot. Each bot ships its own
# admin/settings/bindings.py wiring these to its real backend.
from .settings.bindings import (
    OVERVIEW_FOOTER,
    SETUP_GUIDE_TEXT,
    audit_log_entry,
    get_setting,
    set_setting,
    invalidate_caches,
    is_premium,
    resolve_panel_role,
)
from .permission_checks import (
    check_assignable_role,
    check_bot_guild_permission,
    check_channel_permissions,
    check_role_permissions,
)
from .actions.discord_objects.create import (
    channel_kind_for_types,
    create_channel,
    create_role,
    validate_role_name,
    validator_for_channel_kind,
)
from .settings.panel_configs import MAIN_PANEL
from .views.panel_engine import (
    PanelNode,
    ActionContext,
    PanelInputModal,
    build_menu_view,
    build_overview_view,
    build_select_view,
    build_modal_trigger_view,
    build_dual_modal_trigger_view,
    build_file_upload_view,
    build_dict_editor_view,
    build_dict_key_channel_view,
    build_dict_value_role_view,
    build_paginated_list_view,
    build_confirm_view,
    build_grouped_region_view,
    validate_panel,
    _PanelDualInputModal,
    _child_summary,
    _option_label,
    _get_default_option_value,
)
from .views.base import (
    build_notice_layout,
    build_premium_layout,
    cid,
    create_empty_layout,
    notice_container,
)
from .views.panel_views import PanelSession

logger = logging.getLogger("AdminCog")


class AdminCog(commands.Cog):
    """
    Administrative panel orchestrator.
    Uses Discord Components v2 LayoutViews with config-driven PanelNode trees.

    Multi-message pattern:
      Message 1 -navigation (main panel / category menus)
      Message 2 -settings (followup for leaf settings / sub-menus)
      Message 3 -notifications (ephemeral errors and lock messages)
    """

    AUTOSAVE_COOLDOWN = 2.0  # seconds between autosaves per (user, node_key)

    # -- Lifecycle & Setup -----------------------------------------------------

    def __init__(self, bot: commands.Bot):
        """Initialize the cog and the in-memory autosave cooldown registry."""
        # Fail at load time, naming every offender, if the panel config
        # carries authored text Discord would reject at render time - the
        # text gets rewritten in source, never truncated at runtime.
        validate_panel(MAIN_PANEL)
        self.bot = bot
        self._autosave_cooldowns: dict[tuple, float] = {}
        logger.info("AdminCog initialized")

    # -- Command Groups --------------------------------------------------------

    admin_group = app_commands.Group(
        name="admin",
        description="Admin commands for managing bot configuration",
    )

    def _invalidate_guild_caches(self, guild_id: int) -> None:
        """Invalidate per-guild caches after any settings change (bot-specific)."""
        invalidate_caches(guild_id)

    @staticmethod
    def _resolve_section(node: PanelNode, parent_node: PanelNode | None = None) -> str:
        """Best-effort section label for audit entries.

        A node's explicit ``audit_section`` wins. Otherwise top-level category
        nodes own the section name (e.g. "tictactoe"), falling back to the node's
        own key when no parent context is available.
        """
        if node.audit_section:
            return node.audit_section
        if parent_node is not None and parent_node.key:
            return parent_node.key
        return node.key

    async def _audit(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        node: PanelNode,
        old_value: object,
        new_value: object,
        action: str,
        *,
        parent_node: PanelNode | None = None,
        section: str | None = None,
    ) -> None:
        """Persist an audit entry for a successful admin-driven mutation.

        Failures are swallowed: an audit-write failure must never block a
        user-visible save from appearing successful.
        """
        try:
            await audit_log_entry(
                guild_id=int(guild_id),
                actor_id=int(interaction.user.id),
                actor_name=str(interaction.user),
                section=section or self._resolve_section(node, parent_node),
                key=node.key,
                old_value=old_value,
                new_value=new_value,
                action=action,
            )
        except Exception as e:
            logger.debug(f"Audit log write skipped for {node.key}: {e}")

    @staticmethod
    async def _is_premium(guild_id: int) -> bool:
        """Whether the guild has premium (via the bot's bindings; canonical async)."""
        return await is_premium(guild_id)

    # -- Master Panel (Message 1 -Overview) ------------------------------------

    @admin_group.command(name="panel", description="Open the admin configuration panel")
    async def admin_panel(self, interaction: discord.Interaction):
        """Open the master admin panel (the entry point for the three-message flow).

        Sends Message 1 (the persistent overview) ephemerally, wires the setup-guide
        and details toggles, and registers a PanelSession that synchronizes the
        timeout across this message and any Message 2 followups spawned from it.
        Selecting a category from the overview dropdown delegates to
        `_show_category_on_msg2`, which sends Message 2 as a new followup.
        """
        if not interaction.guild:
            await interaction.response.send_message(
                view=build_notice_layout(
                    "Guild Required",
                    "This command can only be used in a server.",
                ),
                ephemeral=True,
            )
            return

        guild = interaction.guild
        admin_id = interaction.user.id

        # Resolve panel access tier. The panel is admin-only: "admin" or "none".
        panel_role = await resolve_panel_role(interaction.user, guild.id)
        if panel_role == "none":
            await interaction.response.send_message(
                view=build_notice_layout(
                    "Permission Denied",
                    "You do not have permission to use the admin panel. "
                    "Requires **Manage Server** or a configured Panel Access role.",
                ),
                ephemeral=True,
            )
            return

        logger.info(
            f"Admin panel opened by {interaction.user} in guild {guild.id} "
            f"(role={panel_role})"
        )

        # Building the overview reads config for every panel node, which on a cold
        # cache can exceed Discord's 3s interaction window (error 10062 "Unknown
        # interaction"). Acknowledge immediately with a deferred ephemeral response,
        # then deliver the panel via edit_original_response below. Using the ORIGINAL
        # response (not a followup) keeps it the same message the refresh handlers
        # (e.g. on_main_select -> interaction.edit_original_response) already edit.
        await interaction.response.defer(ephemeral=True, thinking=True)

        # Fetch setup guide visibility state
        guide_state = {"hidden": bool(await get_setting("hide_setup_guide", guild.id, default=False))}

        # Config details toggle (compact by default, not persisted)
        details_state = {"expanded": False}

        # Shared session for synced timeout across both messages
        session = PanelSession(interaction)

        async def on_toggle_guide(toggle_interaction: discord.Interaction):
            if not self._check_cooldown(admin_id, "setup_guide_toggle", guild.id):
                await toggle_interaction.response.send_message(
                    "Please wait a moment before toggling again.",
                    ephemeral=True,
                )
                return

            new_hidden = not guide_state["hidden"]
            guide_state["hidden"] = new_hidden

            await set_setting("hide_setup_guide", new_hidden, guild.id)

            layout = await _build_overview()
            await toggle_interaction.response.edit_message(view=self._rebind_session_view(session, layout))

        async def on_toggle_details(toggle_interaction: discord.Interaction):
            if not self._check_cooldown(admin_id, "details_toggle", guild.id):
                await toggle_interaction.response.send_message(
                    "Please wait a moment before toggling again.",
                    ephemeral=True,
                )
                return

            details_state["expanded"] = not details_state["expanded"]
            layout = await _build_overview()
            await toggle_interaction.response.edit_message(view=self._rebind_session_view(session, layout))

        async def on_main_select(sel_interaction: discord.Interaction, child_key: str):
            child = MAIN_PANEL.children.get(child_key)
            if not child:
                return

            # Lock check
            locked = await self._compute_locked_keys(MAIN_PANEL, guild.id)
            if child_key in locked:
                new_locked = await self._compute_locked_keys(MAIN_PANEL, guild.id)
                if child_key in new_locked:
                    reason = MAIN_PANEL.lock_reason or (
                        "Required settings must be configured before "
                        "accessing this option."
                    )
                    notice = build_notice_layout("Setting Locked", reason)
                    refreshed = await _build_overview()
                    await sel_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                    await sel_interaction.followup.send(view=notice, ephemeral=True)
                    return

            # Pre-check gate: a flat panel exposes gated leaves (e.g. the
            # Manage-Server-only panel-access node) directly at the top level,
            # so the gate must run here too, not only inside menu navigation.
            if child.pre_check:
                denied_view = await child.pre_check(sel_interaction, guild.id)
                if denied_view is not None:
                    refreshed = await _build_overview()
                    await sel_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                    await sel_interaction.followup.send(view=denied_view, ephemeral=True)
                    return

            # Auto-close previous message 2
            if session.msg2_message is not None:
                try:
                    await session.msg2_message.edit(
                        view=create_empty_layout("Setting closed. Use the overview above to continue.")
                    )
                except Exception:
                    pass  # Message may have been deleted or interaction expired
                session.clear_msg2()

            # Refresh overview on message 1 so the category Select resets.
            # Without this, Discord keeps the selection highlighted client-side
            # and re-picking the same category won't re-fire the interaction.
            try:
                refreshed = await _build_overview()
                await interaction.edit_original_response(view=self._rebind_session_view(session, refreshed))
            except Exception as e:
                logger.debug(f"Could not refresh overview select state: {e}")

            # Send the child as new message 2 (followup). Only a menu gets the
            # category renderer; a top-level leaf (role_select, option_select,
            # action, ...) must open its real editor - build_menu_view renders a
            # childless node as bare description text with no controls.
            if child.kind == "menu":
                await self._show_category_on_msg2(
                    sel_interaction, child, guild, interaction, admin_id,
                    _build_overview, session,
                )
            else:
                await self._show_leaf_on_msg2(
                    sel_interaction, child, guild, interaction,
                    _build_overview, session,
                )

        async def _build_overview():
            deep_summary = await self._gather_deep_summaries(MAIN_PANEL, guild.id, guild)
            toggle_states = await self._gather_toggle_states(MAIN_PANEL, guild.id)
            locked = await self._compute_locked_keys(MAIN_PANEL, guild.id)

            # Preamble (Setup Guide) is wrapped in a readonly_container by build_overview_view;
            # pass the bare TextDisplay items so the engine can apply the accent color.
            preamble = None
            if not guide_state["hidden"]:
                preamble = [discord.ui.TextDisplay(SETUP_GUIDE_TEXT)]

            guide_btn = discord.ui.Button(
                label="Show Setup Guide" if guide_state["hidden"] else "Hide Setup Guide",
                style=discord.ButtonStyle.secondary,
                custom_id=cid("dash", "toggle_guide"),
            )
            guide_btn.callback = on_toggle_guide

            details_btn = discord.ui.Button(
                label="Hide Config Details" if details_state["expanded"] else "Show Config Details",
                style=discord.ButtonStyle.secondary,
                custom_id=cid("dash", "toggle_details"),
            )
            details_btn.callback = on_toggle_details

            layout = build_overview_view(
                MAIN_PANEL, deep_summary, toggle_states, locked,
                on_main_select,
                preamble_items=preamble,
                extra_buttons=[guide_btn, details_btn],
                compact=not details_state["expanded"],
                footer_text=OVERVIEW_FOOTER or None,
                is_premium=await self._is_premium(guild.id),
            )
            session.register_view(layout)
            return layout

        layout = await _build_overview()
        # Deferred above, so edit the original (thinking) response into the panel
        # instead of send_message. This is the message edit_original_response targets.
        await interaction.edit_original_response(view=layout)
        session.touch()

    # -- Category Menu on Message 2 --------------------------------------------

    async def _show_category_on_msg2(
        self,
        sel_interaction: discord.Interaction,
        category_node: PanelNode,
        guild: discord.Guild,
        original_interaction: discord.Interaction,
        admin_id: int,
        build_overview: Callable[[], Awaitable[discord.ui.LayoutView]],
        session: PanelSession,
    ) -> None:
        """Send a new message 2 (followup) showing a category menu."""

        summary_map = await self._gather_summaries(category_node, guild.id)
        locked_keys = await self._compute_locked_keys(category_node, guild.id)
        _current_locked = [locked_keys]

        toggle_state = None
        if category_node.toggle_get:
            toggle_state = await category_node.toggle_get(guild.id)

        # -- refresh_nav: update the overview on message 1 after saves --
        async def refresh_nav():
            try:
                new_view = await build_overview()
                await original_interaction.edit_original_response(view=self._rebind_session_view(session, new_view))
            except Exception as e:
                logger.debug(f"Could not refresh overview after save: {e}")

        async def _build_category_view():
            new_summary = await self._gather_summaries(category_node, guild.id)
            new_locked = await self._compute_locked_keys(category_node, guild.id)
            _current_locked[0] = new_locked
            new_toggle = await category_node.toggle_get(guild.id) if category_node.toggle_get else None
            return build_menu_view(
                category_node, new_summary, on_child_select, on_back, new_locked,
                toggle_state=new_toggle,
                on_toggle=on_toggle if category_node.toggle_set else None,
                back_label="Done",
                guild_id=guild.id,
                guild=guild,
                is_premium=await self._is_premium(guild.id),
            )

        async def on_child_select(child_interaction: discord.Interaction, child_key: str):
            child = category_node.children.get(child_key)
            if not child:
                return

            # Lock check
            if child_key in _current_locked[0]:
                new_locked = await self._compute_locked_keys(category_node, guild.id)
                if child_key in new_locked:
                    reason = category_node.lock_reason or (
                        "Required settings must be configured before "
                        "accessing this option."
                    )
                    notice = build_notice_layout("Setting Locked", reason)
                    refreshed = await _build_category_view()
                    await child_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                    await child_interaction.followup.send(view=notice, ephemeral=True)
                    return
                else:
                    _current_locked[0] = new_locked
                    refreshed = await _build_category_view()
                    await child_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                    return

            # Pre-check gate
            if child.pre_check:
                denied_view = await child.pre_check(child_interaction, guild.id)
                if denied_view is not None:
                    refreshed = await _build_category_view()
                    await child_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                    await child_interaction.followup.send(view=denied_view, ephemeral=True)
                    return

            # Modal input children -handle inline on message 2
            if child.kind == "modal_input":
                await self._handle_inline_modal(
                    child_interaction, child, category_node, guild,
                    summary_map, on_child_select, on_back,
                    refresh_parent=refresh_nav, session=session,
                )
            else:
                # Navigate within message 2 (edit in-place)
                await self._navigate_to(
                    child_interaction, child, guild,
                    parent_node=category_node,
                    edit=True,
                    refresh_parent=refresh_nav,
                    session=session,
                )

        async def on_back(back_interaction: discord.Interaction):
            # Dismiss message 2
            session.clear_msg2()
            await back_interaction.response.edit_message(
                view=create_empty_layout(
                    "Setting closed. Use the overview above to continue."
                )
            )

        async def on_toggle(toggle_interaction: discord.Interaction):
            if not self._check_cooldown(toggle_interaction.user.id, category_node.key, guild.id):
                await toggle_interaction.response.send_message(
                    "Please wait a moment before toggling again.", ephemeral=True,
                )
                return
            current = await category_node.toggle_get(guild.id)
            success = await category_node.toggle_set(guild.id, not current)
            if success:
                self._invalidate_guild_caches(guild.id)
                if category_node.on_toggle_callback:
                    await category_node.on_toggle_callback(guild, not current)
                action = "disabled" if current else "enabled"
                logger.info(f"Admin {toggle_interaction.user} {action} {category_node.key} in guild {guild.id}")
                await self._audit(
                    toggle_interaction, guild.id, category_node,
                    old_value=bool(current), new_value=not current,
                    action="toggle", section=category_node.key,
                )
                refreshed = await _build_category_view()
                await toggle_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                await refresh_nav()
            else:
                await toggle_interaction.response.send_message(
                    view=build_notice_layout(
                        "Failed to update",
                        f"Could not update **{category_node.label}**.",
                    ),
                    ephemeral=True,
                )

        layout = build_menu_view(
            category_node, summary_map, on_child_select, on_back, locked_keys,
            toggle_state=toggle_state,
            on_toggle=on_toggle if category_node.toggle_set else None,
            back_label="Done",
            guild_id=guild.id,
            guild=guild,
            is_premium=await self._is_premium(guild.id),
        )
        # Send as new followup (message 2)
        session.register_view(layout)
        await sel_interaction.response.send_message(view=layout, ephemeral=True)
        session.set_msg2(layout, await sel_interaction.original_response())

    # -- Top-level leaf on Message 2 --------------------------------------------

    async def _show_leaf_on_msg2(
        self,
        sel_interaction: discord.Interaction,
        leaf_node: PanelNode,
        guild: discord.Guild,
        original_interaction: discord.Interaction,
        build_overview: Callable[[], Awaitable[discord.ui.LayoutView]],
        session: PanelSession,
    ) -> None:
        """Send a new message 2 (followup) showing a top-level leaf's editor.

        A flat panel (ADMIN_PANEL_STANDARD §1) places editable leaves directly
        under the root; those go through the same kind dispatch as menu
        children (`_navigate_to`) so a role_select opens its role picker, an
        option_select its checklist, an action its handler - never the
        category-menu renderer, which shows a childless node as description
        text with no controls.
        """
        async def refresh_nav():
            try:
                new_view = await build_overview()
                await original_interaction.edit_original_response(view=self._rebind_session_view(session, new_view))
            except Exception as e:
                logger.debug(f"Could not refresh overview after save: {e}")

        await self._navigate_to(
            sel_interaction, leaf_node, guild,
            parent_node=None,
            edit=False,
            refresh_parent=refresh_nav,
            session=session,
        )
        # Track message 2 like the category path so the next front-screen pick
        # auto-closes this editor. _navigate_to registered the layout it built.
        try:
            session.set_msg2(
                session.last_registered_view,
                await sel_interaction.original_response(),
            )
        except discord.HTTPException as http_exc:
            logger.debug(f"Could not track leaf msg2: {http_exc}")

    # -- Generic PanelNode Navigator (Message 2) --------------------------------

    async def _navigate_to(
        self,
        interaction: discord.Interaction,
        node: PanelNode,
        guild: discord.Guild,
        *,
        parent_node: PanelNode | None = None,
        grandparent_node: PanelNode | None = None,
        edit: bool = False,
        refresh_parent: Callable[[], Awaitable[None]] | None = None,
        session: PanelSession | None = None,
    ) -> None:
        """Generic navigation for PanelNode trees -renders on message 2.

        When edit=False (default): sends a new followup message (message 2).
        When edit=True: edits the current message 2 in-place (sub-navigation).

        grandparent_node tracks the parent's parent so back-navigation preserves
        the full chain (e.g. leaf -> sub-menu -> category root).
        """
        # §1 nav table: menu root of msg2 uses "Done" (secondary); leaf editors
        # with a parent use "Back". A leaf editor with no parent is the rare
        # "outside the dashboard flow" case and uses "Close".
        if parent_node is None:
            back_label = "Done" if node.kind == "menu" else "Close"
        else:
            back_label = "Back"

        if node.kind == "menu":
            await self._show_menu(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

        elif node.kind in ("role_select", "channel_select", "option_select"):
            await self._show_select(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

        elif node.kind == "modal_input":
            await self._show_modal_trigger(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

        elif node.kind == "dual_modal_input":
            await self._show_dual_modal_trigger(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

        elif node.kind == "file_upload":
            await self._show_file_upload(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

        elif node.kind == "dict_editor":
            await self._show_dict_editor(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

        elif node.kind == "paginated_list":
            await self._show_paginated_list(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

        elif node.kind == "grouped_paginated_select":
            await self._show_grouped_paginated_select(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

        elif node.kind == "action":
            await self._show_action(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

    # -- Action nodes (bot-specific flows behind one extension hook) ------------

    async def _show_action(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Dispatch an ``action``-kind node to its bot-specific handler.

        ``action`` is the single extension point: any interactive flow that doesn't
        fit the generic (guild_id, values) leaf contract (premium activation, bulk
        reset/delete, bespoke multi-step editors) lives in a per-bot module and is
        attached to a node as ``on_run``. The engine just builds the ActionContext
        and hands off - it never needs to know what the handler does.

        Handler contract:  async def on_run(cog, interaction, guild, ctx: ActionContext)
        """
        if node.on_run is None:
            logger.warning(f"action node {node.key!r} has no on_run handler")
            return
        ctx = ActionContext(
            session=session,
            parent_node=parent_node,
            grandparent_node=grandparent_node,
            edit=edit,
            refresh_parent=refresh_parent,
            is_premium=await self._is_premium(guild.id),
            back_label=back_label,
        )
        try:
            await node.on_run(self, interaction, guild, ctx)
        except Exception:
            logger.exception("action handler failed for %s", node.key)
            try:
                notice = build_notice_layout("Something went wrong", f"Could not open **{node.label}**.")
                if interaction.response.is_done():
                    await interaction.followup.send(view=notice, ephemeral=True)
                else:
                    await interaction.response.send_message(view=notice, ephemeral=True)
            except Exception:
                logger.exception("failed to send action failure notice for %s", node.key)

    # -- Node Kind Handlers ----------------------------------------------------
    # -- Menu nodes (on message 2, e.g. counting_roles sub-menu) ---------------

    async def _show_menu(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Render a menu PanelNode on message 2.

        Builds the menu view with current child summaries and lock state,
        wires the dropdown to navigate into children (or open inline modals
        for modal_input children), and supports an optional category-level
        feature toggle. Inline edits refresh both this view and the parent
        overview via `refresh_parent`.
        """
        summary_map = await self._gather_summaries(node, guild.id)
        locked_keys = await self._compute_locked_keys(node, guild.id)
        _current_locked = [locked_keys]

        toggle_state = None
        if node.toggle_get:
            toggle_state = await node.toggle_get(guild.id)

        breadcrumb = " > ".join(
            n.label for n in (grandparent_node, parent_node, node) if n is not None
        ) if parent_node is not None else None

        async def _resolve_menu_description():
            """Live description for this menu when the node defines an
            ``async_description`` (async (guild) -> str). Returns None to fall
            back to the node's static description / description_builder inside
            build_menu_view. Re-resolved on every (re)render so the summary
            reflects current state."""
            if node.async_description is None:
                return None
            try:
                return await node.async_description(guild)
            except Exception:
                logger.exception("async_description failed for %s", node.key)
                return None

        async def _build_current_view():
            new_summary = await self._gather_summaries(node, guild.id)
            new_locked = await self._compute_locked_keys(node, guild.id)
            _current_locked[0] = new_locked
            new_toggle = await node.toggle_get(guild.id) if node.toggle_get else None
            return build_menu_view(
                node, new_summary, on_select, on_cancel, new_locked,
                toggle_state=new_toggle, on_toggle=on_toggle if node.toggle_set else None,
                back_label=back_label,
                guild_id=guild.id,
                guild=guild,
                is_premium=await self._is_premium(guild.id),
                breadcrumb=breadcrumb,
                description_override=await _resolve_menu_description(),
            )

        async def on_select(sel_interaction: discord.Interaction, child_key: str):
            child = node.children.get(child_key)
            if not child:
                return

            # Lock check
            if child_key in _current_locked[0]:
                new_locked = await self._compute_locked_keys(node, guild.id)
                if child_key in new_locked:
                    reason = node.lock_reason or (
                        "Required settings must be configured before "
                        "accessing this option."
                    )
                    notice = build_notice_layout("Setting Locked", reason)
                    refreshed = await _build_current_view()
                    await sel_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                    await sel_interaction.followup.send(view=notice, ephemeral=True)
                    return
                else:
                    _current_locked[0] = new_locked
                    refreshed = await _build_current_view()
                    await sel_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                    return

            # Pre-check gate
            if child.pre_check:
                denied_view = await child.pre_check(sel_interaction, guild.id)
                if denied_view is not None:
                    refreshed = await _build_current_view()
                    await sel_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                    await sel_interaction.followup.send(view=denied_view, ephemeral=True)
                    return

            # Modal input children handled inline from menu
            if child.kind == "modal_input":
                await self._handle_inline_modal(
                    sel_interaction, child, node, guild,
                    summary_map, on_select, on_cancel,
                    refresh_parent=refresh_parent, session=session,
                )
            else:
                # Navigate within message 2 (edit=True)
                # Current parent_node becomes grandparent for the child
                await self._navigate_to(
                    sel_interaction, child, guild,
                    parent_node=node, grandparent_node=parent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )

        async def on_cancel(cancel_interaction: discord.Interaction):
            if parent_node:
                await self._navigate_to(
                    cancel_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await cancel_interaction.response.edit_message(
                    view=create_empty_layout(
                        "Setting closed. Use the overview above to continue."
                    )
                )

        async def on_toggle(toggle_interaction: discord.Interaction):
            if not self._check_cooldown(toggle_interaction.user.id, node.key, guild.id):
                await toggle_interaction.response.send_message(
                    "Please wait a moment before toggling again.", ephemeral=True,
                )
                return
            current = await node.toggle_get(guild.id)
            success = await node.toggle_set(guild.id, not current)
            if success:
                self._invalidate_guild_caches(guild.id)
                if node.on_toggle_callback:
                    await node.on_toggle_callback(guild, not current)
                action = "disabled" if current else "enabled"
                logger.info(f"Admin {toggle_interaction.user} {action} {node.key} in guild {guild.id}")
                await self._audit(
                    toggle_interaction, guild.id, node,
                    old_value=bool(current), new_value=not current,
                    action="toggle", parent_node=parent_node,
                )
                refreshed = await _build_current_view()
                await toggle_interaction.response.edit_message(view=self._rebind_session_view(session, refreshed))
                if refresh_parent:
                    await refresh_parent()
            else:
                await toggle_interaction.response.send_message(
                    view=build_notice_layout(
                        "Failed to update",
                        f"Could not update **{node.label}**.",
                    ),
                    ephemeral=True,
                )

        layout = build_menu_view(
            node, summary_map, on_select, on_cancel, locked_keys,
            toggle_state=toggle_state,
            on_toggle=on_toggle if node.toggle_set else None,
            back_label=back_label,
            guild_id=guild.id,
            guild=guild,
            is_premium=await self._is_premium(guild.id),
            breadcrumb=breadcrumb,
            description_override=await _resolve_menu_description(),
        )
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Select nodes (on message 2) -------------------------------------------

    async def _show_select(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Render a select PanelNode on message 2.

        Handles the role_select / channel_select / option_select kinds via a
        single auto-saving select component. Enforces premium gating
        (`premium_values`, `premium_max_values`) and runs the per-node
        Discord permission checks declared on `node.required_channel_perms`
        and `node.requires_role_manage` before persisting.
        """
        current_values = list(await node.get_values(guild.id)) if node.get_values else []
        premium = await self._is_premium(guild.id)

        async def on_save(save_interaction: discord.Interaction, values: list):
            if not self._check_cooldown(save_interaction.user.id, node.key, guild.id):
                await save_interaction.response.send_message(
                    view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                    ephemeral=True,
                )
                return

            await save_interaction.response.defer(ephemeral=True)

            async def _refuse(notice_view) -> None:
                """Send the refusal AND redraw the editor on its stored values.

                Discord keeps a select's last pick highlighted until the message is
                edited, so without the redraw a refused choice stays selected and the
                admin has to pick something else before they can pick the right thing
                again (owner finding, 2026-08-22). Rebuilt from what is actually saved,
                never from the refused values.
                """
                await save_interaction.followup.send(view=notice_view, ephemeral=True)
                try:
                    stored = list(await node.get_values(guild.id)) if node.get_values else []
                    # Same values as before the pick, so the select must carry a new
                    # custom id or the client keeps the rejected choice highlighted
                    # (seen live 2026-08-22: the card re-rendered, the pick did not).
                    redraw = build_select_view(
                        node, stored, guild, on_save, on_back, on_clear_fn, back_label,
                        is_premium=premium, on_create=on_create_fn, create_label=_create_label,
                        select_nonce=uuid.uuid4().hex[:8],
                    )
                    await save_interaction.edit_original_response(
                        view=self._rebind_session_view(session, redraw)
                    )
                except discord.HTTPException as http_exc:
                    logger.warning("Could not redraw select view after refusal: %s", http_exc)

            # Premium value check
            if node.premium_values and not await self._is_premium(guild.id):
                blocked = [v for v in values if str(v) in node.premium_values]
                if blocked:
                    notice = build_premium_layout(
                        "Premium Required",
                        "This option requires a **Premium** subscription.\n\n"
                        "Use `/premium` to learn more about upgrading.",
                    )
                    await _refuse(notice)
                    return

            # Channel count check for non-premium
            if node.kind == "channel_select" and node.premium_max_values is not None:
                if not await self._is_premium(guild.id) and len(values) > node.max_values:
                    notice = build_premium_layout(
                        "Premium Required",
                        f"Free servers can select up to **{node.max_values}** channel(s).\n"
                        f"Upgrade to **Premium** to select up to **{node.premium_max_values}**.\n\n"
                        "Use `/premium` to learn more about upgrading.",
                    )
                    await _refuse(notice)
                    return

            # Permission pre-check (perms declared on the node itself)
            if node.kind == "channel_select" and values:
                for cid in values:
                    ok, err = check_channel_permissions(node, guild, int(cid))
                    if not ok:
                        await _refuse(build_notice_layout("Permission Issue", err))
                        return
            elif node.kind == "role_select" and values:
                for rid in values:
                    ok, err = check_role_permissions(node, guild, int(rid))
                    if not ok:
                        await _refuse(build_notice_layout("Permission Issue", err))
                        return

            # Value-level validation against live guild state (e.g. channel-in-category).
            if node.value_validator and values:
                err = await node.value_validator(guild, values)
                if err:
                    await _refuse(build_notice_layout("Invalid Selection", err))
                    return

            old_vals = list(await node.get_values(guild.id)) if node.get_values else []
            try:
                success = await node.set_values(guild.id, values)
            except Exception as save_exc:
                logger.exception("Select save failed for node=%s", node.key)
                await _refuse(build_notice_layout(
                    "Failed to save",
                    f"Could not save **{node.label}**. {save_exc.__class__.__name__}",
                ))
                return
            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {save_interaction.user} updated {node.key} in guild {guild.id}")
                await self._audit(
                    save_interaction, guild.id, node,
                    old_value=old_vals, new_value=list(values),
                    action="set", parent_node=parent_node,
                )
                new_layout = build_select_view(
                    node, values, guild, on_save, on_back, on_clear_fn, back_label,
                    is_premium=premium, on_create=on_create_fn, create_label=_create_label,
                )
                try:
                    await save_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                except discord.HTTPException as http_exc:
                    logger.warning("Could not refresh select view: %s", http_exc)
                if node.post_save_hook:
                    await node.post_save_hook(save_interaction, guild.id, values)
                if refresh_parent:
                    await refresh_parent()
            else:
                await _refuse(
                    build_notice_layout("Failed to save", f"Could not save **{node.label}**."),
                )

        async def on_back(back_interaction: discord.Interaction):
            if parent_node:
                # Navigate back to parent on message 2 (edit in-place)
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        on_clear_fn = None
        if node.clear_values:
            async def on_clear(clear_interaction: discord.Interaction):
                if not self._check_cooldown(clear_interaction.user.id, node.key, guild.id):
                    await clear_interaction.response.send_message(
                        view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                        ephemeral=True,
                    )
                    return

                await clear_interaction.response.defer(ephemeral=True)
                old_vals = list(await node.get_values(guild.id)) if node.get_values else []
                success = await node.clear_values(guild.id)
                if success:
                    self._invalidate_guild_caches(guild.id)
                    logger.info(f"Admin {clear_interaction.user} cleared {node.key} in guild {guild.id}")
                    await self._audit(
                        clear_interaction, guild.id, node,
                        old_value=old_vals, new_value=[],
                        action="clear", parent_node=parent_node,
                    )
                    new_layout = build_select_view(
                        node, [], guild, on_save, on_back, on_clear_fn, back_label,
                        is_premium=premium, on_create=on_create_fn, create_label=_create_label,
                    )
                    await clear_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                    if refresh_parent:
                        await refresh_parent()
                else:
                    await clear_interaction.followup.send(
                        view=build_notice_layout("Failed to clear", f"Could not clear **{node.label}**."),
                        ephemeral=True,
                    )

            on_clear_fn = on_clear

        # -- Inline create button (standard §11) --------------------------------
        # Every role/channel select editor lets the admin create the entity right
        # where it is picked - no separate create node. Flow: bot-permission check
        # at the button click -> name modal -> validate -> create -> save through
        # the same checks as picking. Every failure after the modal offers Try
        # Again with the rejected input pre-filled (Discord forbids answering a
        # modal submit with another modal, so the retry is a button hop).
        on_create_fn = None
        _create_label = "Create"
        if node.kind in ("role_select", "channel_select") and node.allow_create:
            _is_role = node.kind == "role_select"
            _chan_kind = None if _is_role else channel_kind_for_types(node.channel_types)
            _create_noun = "Role" if _is_role else {
                "category": "Category", "voice": "Voice Channel",
            }.get(_chan_kind, "Channel")
            _create_label = node.create_label or f"Create {_create_noun}"
            _create_perm = "manage_roles" if _is_role else "manage_channels"
            _name_validator = (
                validate_role_name if _is_role else validator_for_channel_kind(_chan_kind)
            )
            # Text/voice channels get an optional parent-category picker in the
            # create modal (skippable - empty means top of the channel list).
            # Categories cannot nest, and a bot-specific create_entity owns its
            # own creation contract, so neither gets the picker.
            _pick_category = (
                not _is_role
                and _chan_kind in ("text", "voice")
                and node.create_entity is None
            )
            # The select editor is refreshed via the create button's interaction
            # (a component interaction's original response is its host message);
            # a Try Again chain reuses the first button's token.
            _view_bi: list = [None]

            def _entity_display(entity) -> str:
                if not _is_role and _chan_kind == "category":
                    return f"**{entity.name}**"
                return getattr(entity, "mention", f"**{entity.name}**")

            def _create_retry_layout(
                body: str, previous: str, previous_category: Optional[int] = None,
            ) -> discord.ui.LayoutView:
                retry_btn = discord.ui.Button(
                    label="Try Again", style=discord.ButtonStyle.primary,
                    custom_id=cid("editor", "create_retry", node.key),
                )

                async def _retry(ri: discord.Interaction):
                    await _send_create_modal(
                        ri, default=previous, category_default=previous_category,
                    )

                retry_btn.callback = _retry
                retry_row = discord.ui.ActionRow()
                retry_row.add_item(retry_btn)
                layout = discord.ui.LayoutView()
                layout.add_item(notice_container(
                    discord.ui.TextDisplay(f"## {_create_label}\n{body}"), retry_row,
                ))
                return layout

            async def _handle_create_submit(
                mi: discord.Interaction, raw: str, category_id: Optional[int] = None,
            ):
                if not self._check_cooldown(mi.user.id, node.key, guild.id):
                    await mi.response.send_message(
                        view=_create_retry_layout(
                            "Please wait a moment before trying again.", raw, category_id,
                        ),
                        ephemeral=True,
                    )
                    return
                ok, name, error = _name_validator(raw)
                if not ok:
                    await mi.response.send_message(
                        view=_create_retry_layout(
                            error or "That name is not valid.", raw, category_id,
                        ),
                        ephemeral=True,
                    )
                    return
                await mi.response.defer(ephemeral=True)
                category = None
                if _pick_category and category_id is not None:
                    category = guild.get_channel(category_id)
                    if category is None or getattr(category, "type", None) != discord.ChannelType.category:
                        await mi.followup.send(
                            view=_create_retry_layout(
                                "That category no longer exists. Pick another or leave it empty.",
                                raw,
                            ),
                            ephemeral=True,
                        )
                        return

                old_vals = list(await node.get_values(guild.id)) if node.get_values else []

                if node.create_entity is not None:
                    # Bot-specific creator: owns creation AND persistence
                    # (e.g. create-and-configure flows). Contract:
                    # async (guild, name, actor) -> (entity | None, error | None).
                    try:
                        entity, create_err = await node.create_entity(guild, name, mi.user)
                    except Exception:
                        logger.exception("create_entity failed for node=%s", node.key)
                        entity, create_err = None, None
                    if entity is None:
                        await mi.followup.send(
                            view=_create_retry_layout(
                                create_err or f"Could not create the {_create_noun.lower()}.",
                                raw,
                            ),
                            ephemeral=True,
                        )
                        return
                    new_vals = list(await node.get_values(guild.id)) if node.get_values else []
                else:
                    reason = f"Admin panel: created by {mi.user}"
                    if _is_role:
                        entity = await create_role(guild, name, reason=reason)
                    else:
                        extra = {"category": category} if _pick_category else {}
                        entity = await create_channel(
                            guild, name, kind=_chan_kind, reason=reason, **extra,
                        )
                    if entity is None:
                        await mi.followup.send(
                            view=_create_retry_layout(
                                f"Discord refused to create the {_create_noun.lower()}. "
                                "Check the bot's permissions and try again.",
                                raw, category_id,
                            ),
                            ephemeral=True,
                        )
                        return
                    # Creation succeeded - save through the same checks as picking.
                    if node.max_values == 1:
                        new_vals = [entity.id]
                    else:
                        new_vals = [int(v) for v in old_vals if int(v) != entity.id] + [entity.id]
                    if _is_role:
                        perm_ok, err = check_role_permissions(node, guild, entity.id)
                    else:
                        perm_ok, err = check_channel_permissions(node, guild, entity.id)
                    if perm_ok and node.value_validator:
                        err = await node.value_validator(guild, new_vals)
                    elif perm_ok:
                        err = None
                    if err:
                        # Retyping the name will not help here - plain notice, no retry.
                        await mi.followup.send(
                            view=build_notice_layout(
                                "Created but not saved",
                                f"{_entity_display(entity)} was created, but it cannot be "
                                f"saved to **{node.label}**: {err}",
                            ),
                            ephemeral=True,
                        )
                        return
                    try:
                        success = await node.set_values(guild.id, new_vals)
                    except Exception as save_exc:
                        logger.exception("Create save failed for node=%s", node.key)
                        success = False
                        save_detail = f" {save_exc.__class__.__name__}"
                    else:
                        save_detail = ""
                    if not success:
                        await mi.followup.send(
                            view=build_notice_layout(
                                "Created but not saved",
                                f"{_entity_display(entity)} was created, but saving "
                                f"**{node.label}** failed.{save_detail}",
                            ),
                            ephemeral=True,
                        )
                        return

                self._invalidate_guild_caches(guild.id)
                logger.info(
                    f"Admin {mi.user} created {_create_noun.lower()} {entity.id} "
                    f"for {node.key} in guild {guild.id}"
                )
                await self._audit(
                    mi, guild.id, node,
                    old_value=old_vals, new_value=new_vals,
                    action="create", parent_node=parent_node,
                )
                try:
                    fresh = list(await node.get_values(guild.id)) if node.get_values else []
                    new_layout = build_select_view(
                        node, fresh, guild, on_save, on_back, on_clear_fn, back_label,
                        is_premium=premium, on_create=on_create_fn, create_label=_create_label,
                    )
                    if _view_bi[0] is not None:
                        await _view_bi[0].edit_original_response(
                            view=self._rebind_session_view(session, new_layout)
                        )
                except discord.HTTPException as http_exc:
                    logger.warning("Could not refresh select view after create: %s", http_exc)
                if node.post_save_hook and node.create_entity is None:
                    await node.post_save_hook(mi, guild.id, new_vals)
                if refresh_parent:
                    await refresh_parent()
                placed = f" under **{category.name}**" if category is not None else ""
                body = f"Created {_entity_display(entity)}{placed} and saved it to **{node.label}**."
                if _is_role:
                    # Discord puts a new role at the bottom of the list, under every
                    # existing role. Where it sits decides what it outranks and whether
                    # its colour shows, and only a person can move it.
                    body += (
                        "\n\nNew roles start at the bottom of the role list. If this one "
                        "needs to sit above other roles (to outrank them, or to show its "
                        "colour on names), move it in Server Settings -> Roles."
                    )
                await mi.followup.send(
                    view=build_notice_layout(_create_label, body),
                    ephemeral=True,
                )

            async def _send_create_modal(
                bi: discord.Interaction, default: str = "",
                category_default: Optional[int] = None,
            ):
                modal = PanelInputModal(
                    title=_create_label[:45],
                    label=f"{_create_noun} name",
                    placeholder="",
                    min_length=1,
                    max_length=100,
                    default=default,
                    on_submit_callback=_handle_create_submit,
                    category_picker=_pick_category,
                    category_default=category_default,
                )
                await bi.response.send_modal(modal)

            async def on_create(create_interaction: discord.Interaction):
                perm_ok, perm_err = check_bot_guild_permission(guild, _create_perm)
                if not perm_ok:
                    await create_interaction.response.send_message(
                        view=build_notice_layout("Missing Permission", perm_err or ""),
                        ephemeral=True,
                    )
                    return
                # A full multi-select is refused before the modal - never create
                # an entity there is no room to save.
                if node.create_entity is None and node.max_values > 1:
                    effective_max = node.max_values
                    if node.premium_max_values is not None and await self._is_premium(guild.id):
                        effective_max = node.premium_max_values
                    current = list(await node.get_values(guild.id)) if node.get_values else []
                    if len(current) >= effective_max:
                        await create_interaction.response.send_message(
                            view=build_notice_layout(
                                "Selection Full",
                                f"**{node.label}** already holds the maximum of "
                                f"**{effective_max}**. Remove one first.",
                            ),
                            ephemeral=True,
                        )
                        return
                _view_bi[0] = create_interaction
                await _send_create_modal(create_interaction)

            on_create_fn = on_create

        layout = build_select_view(
            node, current_values, guild, on_save, on_back, on_clear_fn, back_label,
            is_premium=premium, on_create=on_create_fn, create_label=_create_label,
        )
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Modal trigger nodes (on message 2) ------------------------------------

    async def _show_modal_trigger(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Render a modal_input PanelNode on message 2.

        Shows the current value and a Set button that opens `PanelInputModal`
        pre-filled with the current value. Validates submitted text via
        `node.modal_validator`, supports clearing when `node.clear_values` is
        defined, and refreshes the parent overview after each save.
        """
        current_values = list(await node.get_values(guild.id)) if node.get_values else []

        async def on_save(button_interaction, modal_interaction, raw_value):
            if node.modal_validator:
                ok, value, error = node.modal_validator(raw_value)
                if not ok:
                    # Validation failure: orange notice + rebuild Message 2 with attempted value
                    # so the user can re-open the modal pre-filled and correct it.
                    await modal_interaction.response.send_message(
                        view=build_notice_layout("Invalid Input", error or "Please try again."),
                        ephemeral=True,
                    )
                    try:
                        new_vals = list(await node.get_values(guild.id)) if node.get_values else []
                        retry_layout = build_modal_trigger_view(
                            node, new_vals, guild, on_save, on_back, on_clear_fn, back_label,
                            attempted=raw_value,
                            is_premium=await self._is_premium(guild.id),
                        )
                        await button_interaction.edit_original_response(view=self._rebind_session_view(session, retry_layout))
                    except discord.HTTPException as http_exc:
                        logger.warning("Could not rebuild modal trigger after validation fail: %s", http_exc)
                    return
            else:
                value = raw_value

            if not self._check_cooldown(button_interaction.user.id, node.key, guild.id):
                await modal_interaction.response.send_message(
                    view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                    ephemeral=True,
                )
                return

            await modal_interaction.response.defer(ephemeral=True)

            old_vals = list(await node.get_values(guild.id)) if node.get_values else []
            cleared = not value and node.clear_values
            try:
                if cleared:
                    success = await node.clear_values(guild.id)
                else:
                    success = await node.set_values(guild.id, [value])
            except Exception as save_exc:
                logger.exception("Save failed for node=%s", node.key)
                await modal_interaction.followup.send(
                    view=build_notice_layout(
                        "Failed to save",
                        f"Could not save **{node.label}**. {save_exc.__class__.__name__}",
                    ),
                    ephemeral=True,
                )
                return

            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {button_interaction.user} updated {node.key} in guild {guild.id}")
                new_vals = list(await node.get_values(guild.id)) if node.get_values else []
                await self._audit(
                    button_interaction, guild.id, node,
                    old_value=old_vals,
                    new_value=[] if cleared else [value],
                    action="clear" if cleared else "set",
                    parent_node=parent_node,
                )
                new_layout = build_modal_trigger_view(node, new_vals, guild, on_save, on_back, on_clear_fn, back_label, is_premium=await self._is_premium(guild.id))
                try:
                    await button_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                except discord.HTTPException as http_exc:
                    logger.warning("Could not refresh modal trigger view: %s", http_exc)
                if node.post_save_hook:
                    await node.post_save_hook(modal_interaction, guild.id, [value])
                if refresh_parent:
                    await refresh_parent()
            else:
                await modal_interaction.followup.send(
                    view=build_notice_layout(
                        "Failed to save",
                        f"Could not save **{node.label}**.",
                    ),
                    ephemeral=True,
                )

        async def on_back(back_interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        on_clear_fn = None
        if node.clear_values:
            async def on_clear(clear_interaction):
                if not self._check_cooldown(clear_interaction.user.id, node.key, guild.id):
                    await clear_interaction.response.send_message(
                        view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                        ephemeral=True,
                    )
                    return
                await clear_interaction.response.defer(ephemeral=True)
                old_vals = list(await node.get_values(guild.id)) if node.get_values else []
                success = await node.clear_values(guild.id)
                if success:
                    self._invalidate_guild_caches(guild.id)
                    logger.info(f"Admin {clear_interaction.user} cleared {node.key} in guild {guild.id}")
                    await self._audit(
                        clear_interaction, guild.id, node,
                        old_value=old_vals, new_value=[],
                        action="clear", parent_node=parent_node,
                    )
                    new_layout = build_modal_trigger_view(node, [], guild, on_save, on_back, on_clear_fn, back_label, is_premium=await self._is_premium(guild.id))
                    await clear_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                    if refresh_parent:
                        await refresh_parent()
                else:
                    await clear_interaction.followup.send(
                        view=build_notice_layout("Failed to clear", f"Could not clear **{node.label}**."),
                        ephemeral=True,
                    )

            on_clear_fn = on_clear

        layout = build_modal_trigger_view(node, current_values, guild, on_save, on_back, on_clear_fn, back_label, is_premium=await self._is_premium(guild.id))
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Dual modal trigger nodes (on message 2) --------------------------------

    async def _show_dual_modal_trigger(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Render a dual_modal_input PanelNode on message 2.

        Shows both stored fields and an Edit button that opens a two-field modal
        pre-filled with the current values. Persists `[val1, val2]` via
        `node.set_values` and refreshes the parent overview on success.
        """
        current_values = list(await node.get_values(guild.id)) if node.get_values else []

        async def on_save(button_interaction, modal_interaction, val1, val2):
            if not self._check_cooldown(button_interaction.user.id, node.key, guild.id):
                await modal_interaction.response.send_message(
                    view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                    ephemeral=True,
                )
                return

            await modal_interaction.response.defer(ephemeral=True)
            old_vals = list(await node.get_values(guild.id)) if node.get_values else []
            success = await node.set_values(guild.id, [val1, val2])
            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {button_interaction.user} updated {node.key} in guild {guild.id}")
                new_vals = list(await node.get_values(guild.id)) if node.get_values else []
                await self._audit(
                    button_interaction, guild.id, node,
                    old_value=old_vals, new_value=[val1, val2],
                    action="set", parent_node=parent_node,
                )
                new_layout = build_dual_modal_trigger_view(node, new_vals, guild, on_save, on_back, back_label, is_premium=await self._is_premium(guild.id))
                try:
                    await button_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                except discord.HTTPException as http_exc:
                    logger.warning("Could not refresh dual modal view: %s", http_exc)
                if refresh_parent:
                    await refresh_parent()
            else:
                await modal_interaction.followup.send(
                    view=build_notice_layout("Failed to save", f"Could not save **{node.label}**."),
                    ephemeral=True,
                )

        async def on_back(back_interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        layout = build_dual_modal_trigger_view(node, current_values, guild, on_save, on_back, back_label, is_premium=await self._is_premium(guild.id))
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- File upload nodes (on message 2) --------------------------------------

    async def _show_file_upload(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Render a file_upload PanelNode on message 2.

        Wires Upload (opens PanelFileUploadModal) -> node.set_values([attachment]),
        and Clear -> node.clear_values(). Refreshes the view in place after each
        action and bubbles a refresh up to message 1 via refresh_parent.
        """
        current_values = list(await node.get_values(guild.id)) if node.get_values else []

        async def on_upload(button_interaction, modal_interaction, attachment):
            if not self._check_cooldown(button_interaction.user.id, node.key, guild.id):
                await modal_interaction.response.send_message(
                    view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                    ephemeral=True,
                )
                return
            await modal_interaction.response.defer(ephemeral=True)

            # Upload contract: the engine reads the attachment and hands set_values the
            # decoded UTF-8 text (str) -- never the raw discord.Attachment. When the node
            # declares a schema_validator it runs against the PARSED JSON payload here,
            # before anything is persisted (see PanelNode.schema_validator).
            try:
                raw_bytes = await attachment.read()
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                await modal_interaction.followup.send(
                    view=build_notice_layout("Invalid file", "The uploaded file is not valid UTF-8 text."),
                    ephemeral=True,
                )
                return
            except Exception as read_exc:
                logger.exception("Failed to read upload for node=%s", node.key)
                await modal_interaction.followup.send(
                    view=build_notice_layout(
                        "Upload failed", f"Could not read the file. {read_exc.__class__.__name__}",
                    ),
                    ephemeral=True,
                )
                return

            if node.schema_validator:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as json_exc:
                    await modal_interaction.followup.send(
                        view=build_notice_layout("Invalid JSON", f"The file is not valid JSON: {json_exc}"),
                        ephemeral=True,
                    )
                    return
                ok, error = node.schema_validator(parsed)
                if not ok:
                    await modal_interaction.followup.send(
                        view=build_notice_layout("Invalid file", error or "The file did not pass validation."),
                        ephemeral=True,
                    )
                    return

            try:
                success = await node.set_values(guild.id, [text])
            except Exception as save_exc:
                logger.exception("Upload save failed for node=%s", node.key)
                await modal_interaction.followup.send(
                    view=build_notice_layout(
                        "Failed to upload", f"Could not save **{node.label}**. {save_exc.__class__.__name__}",
                    ),
                    ephemeral=True,
                )
                return
            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {button_interaction.user} uploaded {node.key} in guild {guild.id}")
                new_vals = list(await node.get_values(guild.id)) if node.get_values else []
                await self._audit(
                    button_interaction, guild.id, node,
                    old_value=None,
                    new_value=getattr(attachment, "filename", "uploaded"),
                    action="set", parent_node=parent_node,
                )
                new_layout = build_file_upload_view(
                    node, new_vals, guild, on_back, on_clear_fn, back_label, on_upload=on_upload,
                    is_premium=await self._is_premium(guild.id),
                )
                try:
                    await button_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                except discord.HTTPException as http_exc:
                    logger.warning("Could not refresh file upload view: %s", http_exc)
                if node.post_save_hook:
                    await node.post_save_hook(modal_interaction, guild.id, [attachment])
                if refresh_parent:
                    await refresh_parent()
            else:
                await modal_interaction.followup.send(
                    view=build_notice_layout("Failed to upload", f"Could not upload **{node.label}**."),
                    ephemeral=True,
                )

        async def on_back(back_interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        on_clear_fn = None
        if node.clear_values:
            async def on_clear(clear_interaction):
                if not self._check_cooldown(clear_interaction.user.id, node.key, guild.id):
                    await clear_interaction.response.send_message(
                        view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                        ephemeral=True,
                    )
                    return
                await clear_interaction.response.defer(ephemeral=True)
                success = await node.clear_values(guild.id)
                if success:
                    self._invalidate_guild_caches(guild.id)
                    logger.info(f"Admin {clear_interaction.user} cleared {node.key} in guild {guild.id}")
                    await self._audit(
                        clear_interaction, guild.id, node,
                        old_value=None, new_value=None,
                        action="clear", parent_node=parent_node,
                    )
                    new_layout = build_file_upload_view(
                        node, [], guild, on_back, on_clear_fn, back_label, on_upload=on_upload,
                        is_premium=await self._is_premium(guild.id),
                    )
                    try:
                        await clear_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                    except discord.HTTPException as http_exc:
                        logger.warning("Could not refresh file upload view after clear: %s", http_exc)
                    if refresh_parent:
                        await refresh_parent()
                else:
                    await clear_interaction.followup.send(
                        view=build_notice_layout("Failed to clear", f"Could not clear **{node.label}**."),
                        ephemeral=True,
                    )

            on_clear_fn = on_clear

        layout = build_file_upload_view(
            node, current_values, guild, on_back, on_clear_fn, back_label, on_upload=on_upload,
            is_premium=await self._is_premium(guild.id),
        )
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Dict editor nodes (on message 2) --------------------------------------

    async def _show_dict_editor(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Render a dict_editor PanelNode on message 2.

        Generic key->value map editor. Buttons: Add, Edit (select an existing key),
        Remove (select an existing key). Persists through node.dict_set_value /
        node.dict_remove_value, validating the key via node.dict_key_validator and
        the value via node.dict_value_validator when present.

        The input shape follows node.dict_key_kind / node.dict_value_kind, so an
        admin never has to type a snowflake id:
          text -> text (both default): one dual-field modal, exactly as before.
          channel -> text: Add opens a ChannelSelect screen, then the value modal;
              Edit re-opens only the value modal, because a channel key is fixed
              (change one by removing the entry and adding it again).
          text -> role: Add opens a one-field key modal, then a RoleSelect screen;
              Edit re-opens the key modal pre-filled, then the RoleSelect
              pre-filled, so both the key and the role can change.
          channel -> role: both screens, no modal at all (a channel key is fixed,
              so Edit goes straight to the RoleSelect).
        Role values are permission-checked before they are persisted (Manage Roles,
        role exists, never @everyone, never integration-managed, below the bot's
        top role).
        """
        key_is_channel = node.dict_key_kind == "channel"
        value_is_role = node.dict_value_kind == "role"

        async def fetch_current() -> dict:
            try:
                return dict(await node.dict_get_values(guild.id)) if node.dict_get_values else {}
            except Exception:
                return {}

        async def _build_view():
            current = await fetch_current()
            return build_dict_editor_view(
                node, current,
                on_add=on_add,
                on_edit=on_edit,
                on_remove=on_remove,
                on_back=on_back,
                back_label=back_label,
                is_premium=await self._is_premium(guild.id),
                guild=guild,
            )

        def _validate_key(raw_key) -> tuple[bool, str, str]:
            """Return (ok, normalized_key, error) for a candidate key.

            An empty key is always rejected. When the node supplies a
            dict_key_validator it also parses/normalizes the key, and a parsed
            value that is not None is stored in its string form (so a typed key
            such as "05" lands as "5").
            """
            key = str(raw_key).strip()
            if not key:
                return False, "", "Key cannot be empty."
            if node.dict_key_validator:
                ok, error_msg, parsed = node.dict_key_validator(key)
                if not ok:
                    return False, key, error_msg or "Invalid key."
                if parsed is not None:
                    key = str(parsed)
            return True, key, ""

        async def _persist(ui_interaction, resp_interaction, raw_key, raw_value, *, original_key=None):
            """Validate and write a single entry.

            ``ui_interaction`` owns message 2 - its original response is refreshed
            with the rebuilt editor on success. ``resp_interaction`` is the one
            Discord is still waiting on and must be answered. They are the same
            interaction whenever the final step is a component (the role picker)
            instead of a modal.
            """
            ok, key, error_msg = _validate_key(raw_key)
            if not ok:
                await resp_interaction.response.send_message(
                    view=build_notice_layout("Invalid Key", error_msg),
                    ephemeral=True,
                )
                return

            # A channel key honors the node's required_channel_perms, same as a
            # channel_select leaf - without it a per-channel entry can point at a
            # channel the bot cannot even see, leaving the setting silently inert.
            if key_is_channel and node.required_channel_perms:
                try:
                    perm_ok, perm_err = check_channel_permissions(node, guild, int(key))
                except (TypeError, ValueError):
                    perm_ok, perm_err = False, "That channel could not be read. Please pick it again."
                if not perm_ok:
                    await resp_interaction.response.send_message(
                        view=build_notice_layout("Permission Issue", perm_err),
                        ephemeral=True,
                    )
                    return

            if value_is_role:
                # A role this bot is expected to hand out must always clear the same
                # bar as a requires_role_manage role_select.
                try:
                    role_id = int(raw_value)
                except (TypeError, ValueError):
                    await resp_interaction.response.send_message(
                        view=build_notice_layout(
                            "Invalid Role", "That role could not be read. Please pick it again.",
                        ),
                        ephemeral=True,
                    )
                    return
                perm_ok, perm_err = check_assignable_role(guild, role_id)
                if not perm_ok:
                    await resp_interaction.response.send_message(
                        view=build_notice_layout("Permission Issue", perm_err),
                        ephemeral=True,
                    )
                    return
                value = str(role_id)
            elif node.dict_value_validator:
                ok, error_msg, parsed = node.dict_value_validator(raw_value)
                if not ok:
                    await resp_interaction.response.send_message(
                        view=build_notice_layout(
                            "Invalid Value", error_msg or "Invalid value.",
                        ),
                        ephemeral=True,
                    )
                    return
                value = parsed
            else:
                value = raw_value

            if not self._check_cooldown(ui_interaction.user.id, node.key, guild.id):
                await resp_interaction.response.send_message(
                    view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                    ephemeral=True,
                )
                return
            await resp_interaction.response.defer(ephemeral=True)

            current = await fetch_current()
            if (
                node.dict_max_entries is not None
                and original_key is None
                and key not in current
                and len(current) >= node.dict_max_entries
            ):
                await resp_interaction.followup.send(
                    view=build_notice_layout(
                        "Limit Reached",
                        f"Maximum **{node.dict_max_entries}** entries reached.",
                    ),
                    ephemeral=True,
                )
                return

            success = await node.dict_set_value(guild.id, key, value) if node.dict_set_value else False
            # Rename: remove the OLD key only after the new value is safely written,
            # so a failed write can't leave the entry deleted with no replacement.
            if success and original_key is not None and original_key != key and node.dict_remove_value:
                await node.dict_remove_value(guild.id, original_key)
            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {ui_interaction.user} updated {node.key}[{key}] in guild {guild.id}")
                await self._audit(
                    ui_interaction, guild.id, node,
                    old_value={original_key: current.get(original_key)} if original_key else None,
                    new_value={key: value},
                    action="set", parent_node=parent_node,
                    section=node.key,
                )
                new_layout = await _build_view()
                try:
                    await ui_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                except discord.HTTPException as http_exc:
                    logger.warning("Could not refresh dict editor: %s", http_exc)
                if refresh_parent:
                    await refresh_parent()
            else:
                await resp_interaction.followup.send(
                    view=build_notice_layout(
                        "Failed to save",
                        f"Could not save **{node.label}** entry.",
                    ),
                    ephemeral=True,
                )

        # -- Picker steps (only reached when a new dict_*_kind is set) ----------

        async def on_picker_back(back_interaction: discord.Interaction):
            """Leave a picker step without changing anything - back to the entries."""
            await back_interaction.response.edit_message(
                view=self._rebind_session_view(session, await _build_view())
            )

        async def _open_value_modal(trigger_interaction, key, *, original_key, default_value=""):
            """One-field value modal for an already-decided key (channel-key flow)."""
            async def _submit(mi, raw):
                await _persist(trigger_interaction, mi, key, raw, original_key=original_key)

            modal = PanelInputModal(
                title=(f"Edit {node.label}" if original_key is not None else f"Add {node.label}")[:45],
                label=(node.dict_value_label or "Value")[:45],
                placeholder="",
                min_length=1,
                max_length=node.modal_max_length_2 or 500,
                default=default_value,
                on_submit_callback=_submit,
            )
            await trigger_interaction.response.send_modal(modal)

        def _make_role_pick(entry_key, original_key):
            """Bind one entry's key to the role picker's pick callback."""
            async def _on_role_pick(role_interaction: discord.Interaction, role_id: int):
                await _persist(
                    role_interaction, role_interaction, entry_key, str(role_id),
                    original_key=original_key,
                )

            return _on_role_pick

        async def _role_picker_layout(entry_key, original_key, current_role_id):
            return build_dict_value_role_view(
                node, entry_key,
                current_role_id=current_role_id,
                on_pick=_make_role_pick(entry_key, original_key),
                on_back=on_picker_back,
                back_label="Back",
                is_premium=await self._is_premium(guild.id),
                guild=guild,
            )

        async def _continue_after_key(component_interaction, key, original_key, current_value):
            """Run the value step for a key just chosen on a component screen."""
            if value_is_role:
                layout = await _role_picker_layout(key, original_key, current_value)
                await component_interaction.response.edit_message(
                    view=self._rebind_session_view(session, layout)
                )
            else:
                await _open_value_modal(
                    component_interaction, key,
                    original_key=original_key,
                    default_value="" if current_value is None else str(current_value),
                )

        async def on_channel_pick(channel_interaction: discord.Interaction, channel_id: int):
            current = await fetch_current()
            key = str(channel_id)
            # Picking a channel that already has an entry edits that entry rather
            # than tripping the max-entries guard with a duplicate.
            await _continue_after_key(
                channel_interaction, key,
                key if key in current else None,
                current.get(key),
            )

        async def on_add(bi: discord.Interaction):
            if key_is_channel:
                layout = build_dict_key_channel_view(
                    node,
                    on_pick=on_channel_pick,
                    on_back=on_picker_back,
                    back_label="Back",
                    is_premium=await self._is_premium(guild.id),
                )
                await bi.response.edit_message(view=self._rebind_session_view(session, layout))
                return

            if value_is_role:
                async def _submit_key(mi: discord.Interaction, raw_key: str):
                    ok, key, error_msg = _validate_key(raw_key)
                    if not ok:
                        await mi.response.send_message(
                            view=build_notice_layout("Invalid Key", error_msg),
                            ephemeral=True,
                        )
                        return
                    current = await fetch_current()
                    if (
                        node.dict_max_entries is not None
                        and key not in current
                        and len(current) >= node.dict_max_entries
                    ):
                        await mi.response.send_message(
                            view=build_notice_layout(
                                "Limit Reached",
                                f"Maximum **{node.dict_max_entries}** entries reached.",
                            ),
                            ephemeral=True,
                        )
                        return
                    # The role picker is a screen, not a modal: acknowledge the modal
                    # submit, then swap message 2 (the Add button's message) to it.
                    await mi.response.defer(ephemeral=True)
                    layout = await _role_picker_layout(
                        key, key if key in current else None, current.get(key),
                    )
                    try:
                        await bi.edit_original_response(view=self._rebind_session_view(session, layout))
                    except discord.HTTPException as http_exc:
                        logger.warning("Could not open role picker for %s: %s", node.key, http_exc)

                modal = PanelInputModal(
                    title=f"Add {node.label}"[:45],
                    label=(node.dict_key_label or "Key")[:45],
                    placeholder="",
                    min_length=1,
                    max_length=node.modal_max_length,
                    default="",
                    on_submit_callback=_submit_key,
                )
                await bi.response.send_modal(modal)
                return

            async def _submit(mi, raw1, raw2):
                await _persist(bi, mi, raw1, raw2)

            modal = _PanelDualInputModal(
                title=f"Add {node.label}"[:45],
                label=node.dict_key_label or "Key",
                placeholder="",
                min_length=1,
                max_length=node.modal_max_length,
                default="",
                label_2=node.dict_value_label or "Value",
                placeholder_2="",
                min_length_2=0,
                max_length_2=node.modal_max_length_2 or 500,
                default_2="",
                on_submit_callback=_submit,
            )
            await bi.response.send_modal(modal)

        async def on_edit(bi: discord.Interaction, original_key: str):
            current = await fetch_current()
            current_value = current.get(original_key, "")

            if key_is_channel and value_is_role:
                # A channel key is fixed - editing changes only the role. Change a
                # key by removing the entry and adding it again.
                layout = await _role_picker_layout(
                    str(original_key), original_key, current_value,
                )
                await bi.response.edit_message(view=self._rebind_session_view(session, layout))
                return

            if value_is_role:
                # A text key is editable: re-open the key modal pre-filled, then
                # the role picker - the same two steps as Add. _persist handles the
                # rename (write new key, then drop the old one).
                async def _submit_key(mi: discord.Interaction, raw_key: str):
                    ok, key, error_msg = _validate_key(raw_key)
                    if not ok:
                        await mi.response.send_message(
                            view=build_notice_layout("Invalid Key", error_msg),
                            ephemeral=True,
                        )
                        return
                    # The role picker is a screen, not a modal: acknowledge the modal
                    # submit, then swap message 2 (the edit select's message) to it.
                    await mi.response.defer(ephemeral=True)
                    layout = await _role_picker_layout(key, original_key, current_value)
                    try:
                        await bi.edit_original_response(view=self._rebind_session_view(session, layout))
                    except discord.HTTPException as http_exc:
                        logger.warning("Could not open role picker for %s: %s", node.key, http_exc)

                modal = PanelInputModal(
                    title=f"Edit {node.label}"[:45],
                    label=(node.dict_key_label or "Key")[:45],
                    placeholder="",
                    min_length=1,
                    max_length=node.modal_max_length,
                    default=str(original_key),
                    on_submit_callback=_submit_key,
                )
                await bi.response.send_modal(modal)
                return

            if key_is_channel:
                # A channel key is fixed - editing changes only the value. Change a
                # key by removing the entry and adding it again.
                await _open_value_modal(
                    bi, str(original_key),
                    original_key=original_key,
                    default_value=str(current_value),
                )
                return

            async def _submit(mi, raw1, raw2):
                await _persist(bi, mi, raw1, raw2, original_key=original_key)

            modal = _PanelDualInputModal(
                title=f"Edit {original_key}"[:45],
                label=node.dict_key_label or "Key",
                placeholder="",
                min_length=1,
                max_length=node.modal_max_length,
                default=str(original_key),
                label_2=node.dict_value_label or "Value",
                placeholder_2="",
                min_length_2=0,
                max_length_2=node.modal_max_length_2 or 500,
                default_2=str(current_value),
                on_submit_callback=_submit,
            )
            await bi.response.send_modal(modal)

        async def on_remove(remove_interaction: discord.Interaction, target_key: str):
            if not self._check_cooldown(remove_interaction.user.id, node.key, guild.id):
                await remove_interaction.response.send_message(
                    view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                    ephemeral=True,
                )
                return
            await remove_interaction.response.defer(ephemeral=True)
            old_map = await fetch_current()
            success = await node.dict_remove_value(guild.id, target_key) if node.dict_remove_value else False
            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {remove_interaction.user} removed {node.key}[{target_key}] in guild {guild.id}")
                await self._audit(
                    remove_interaction, guild.id, node,
                    old_value={target_key: old_map.get(target_key)},
                    new_value=None,
                    action="remove", parent_node=parent_node,
                    section=node.key,
                )
                new_layout = await _build_view()
                try:
                    await remove_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                except discord.HTTPException as http_exc:
                    logger.warning("Could not refresh dict editor after remove: %s", http_exc)
                if refresh_parent:
                    await refresh_parent()
            else:
                await remove_interaction.followup.send(
                    view=build_notice_layout(
                        "Failed to remove",
                        f"Could not remove **{target_key}** from {node.label}.",
                    ),
                    ephemeral=True,
                )

        async def on_back(back_interaction: discord.Interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        layout = await _build_view()
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Paginated list nodes (on message 2) -----------------------------------

    async def _show_paginated_list(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Render a paginated_list PanelNode on message 2.

        Browses ``node.list_get_items`` in pages of ``node.list_page_size``; an
        optional destructive per-item action (``node.list_action``) runs behind a
        Confirm/Cancel step. The per-item Select is bounded to the current page,
        so it never exceeds Discord's 25-option cap.
        """
        page_size = max(1, node.list_page_size)
        page_state = {"page": 0}
        is_premium = await self._is_premium(guild.id)

        async def _fetch_items() -> list:
            if node.list_get_items is None:
                return []
            try:
                return list(await node.list_get_items(guild.id))
            except Exception as e:
                logger.exception(f"Failed to load list items for {node.key}: {e}")
                return []

        async def _build_list_layout() -> discord.ui.LayoutView:
            items = await _fetch_items()
            total = len(items)
            total_pages = max(1, (total + page_size - 1) // page_size)
            page_state["page"] = max(0, min(page_state["page"], total_pages - 1))
            start = page_state["page"] * page_size
            page_items = items[start:start + page_size]
            return build_paginated_list_view(
                node, page_items, page_state["page"], total, guild,
                on_list_prev, on_list_next, on_list_pick, on_list_back,
                back_label, is_premium=is_premium, on_extra=on_list_extra,
            )

        async def on_list_extra(extra_interaction: discord.Interaction):
            """Run the node's extra action (a create wizard, typically) under the
            same contract as an action node's ``on_run``. ``ctx.parent_node`` is
            THIS list node, so a flow's back-to-panel lands back on the list."""
            if node.list_extra_action is None:
                return
            ctx = ActionContext(
                session=session,
                parent_node=node,
                grandparent_node=parent_node,
                edit=True,
                refresh_parent=refresh_parent,
                is_premium=is_premium,
                back_label=back_label,
            )
            try:
                await node.list_extra_action(self, extra_interaction, guild, ctx)
            except Exception:
                logger.exception("list extra action failed for %s", node.key)
                try:
                    notice = build_notice_layout(
                        "Something went wrong",
                        f"Could not open **{node.list_extra_action_label or node.label}**.",
                    )
                    if extra_interaction.response.is_done():
                        await extra_interaction.followup.send(view=notice, ephemeral=True)
                    else:
                        await extra_interaction.response.send_message(view=notice, ephemeral=True)
                except Exception:
                    logger.exception("failed to send extra-action failure notice for %s", node.key)

        async def on_list_prev(prev_interaction: discord.Interaction):
            page_state["page"] = max(0, page_state["page"] - 1)
            await prev_interaction.response.edit_message(view=self._rebind_session_view(session, await _build_list_layout()))

        async def on_list_next(next_interaction: discord.Interaction):
            page_state["page"] += 1
            await next_interaction.response.edit_message(view=self._rebind_session_view(session, await _build_list_layout()))

        async def on_list_back(back_interaction: discord.Interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        async def on_list_pick(pick_interaction: discord.Interaction, value: str):
            if node.list_action is None:
                return
            items = await _fetch_items()
            chosen = next(
                (it for it in items if str(node.list_item_value(it)) == str(value)),
                None,
            )
            if chosen is None:
                # Item already gone (deleted elsewhere / list refreshed) - re-render.
                await pick_interaction.response.edit_message(view=self._rebind_session_view(session, await _build_list_layout()))
                return

            confirm_text = (
                node.list_action_confirm_line(chosen)
                if node.list_action_confirm_line is not None
                else node.list_format_line(chosen, 0)
            )
            action_label = node.list_action_label or "Confirm"

            async def on_list_confirm(confirm_interaction: discord.Interaction):
                if not self._check_cooldown(confirm_interaction.user.id, node.key, guild.id):
                    await confirm_interaction.response.send_message(
                        view=build_notice_layout("Slow Down", "Please wait a moment before trying again."),
                        ephemeral=True,
                    )
                    return
                await confirm_interaction.response.defer(ephemeral=True)
                try:
                    success = await node.list_action(guild.id, value)
                except Exception as e:
                    logger.exception(f"List action failed for {node.key} ({value}): {e}")
                    success = False

                if success:
                    self._invalidate_guild_caches(guild.id)
                    logger.info(
                        f"Admin {confirm_interaction.user} ran '{action_label}' on "
                        f"{node.key} ({value}) in guild {guild.id}"
                    )
                    await self._audit(
                        confirm_interaction, guild.id, node,
                        old_value=str(value), new_value=None,
                        action="delete", parent_node=parent_node,
                    )
                    try:
                        await confirm_interaction.edit_original_response(view=self._rebind_session_view(session, await _build_list_layout()))
                    except discord.HTTPException as http_exc:
                        logger.warning("Could not refresh paginated list: %s", http_exc)
                    if refresh_parent:
                        await refresh_parent()
                else:
                    await confirm_interaction.followup.send(
                        view=build_notice_layout(
                            "Failed",
                            f"Failed to {action_label.lower()} the selected item.",
                        ),
                        ephemeral=True,
                    )

            async def on_list_cancel(cancel_interaction: discord.Interaction):
                await cancel_interaction.response.edit_message(view=self._rebind_session_view(session, await _build_list_layout()))

            confirm_layout = build_confirm_view(
                f"{action_label}?",
                confirm_text,
                on_list_confirm,
                on_list_cancel,
                confirm_label=action_label,
                key=node.key,
            )
            await pick_interaction.response.edit_message(view=self._rebind_session_view(session, confirm_layout))

        layout = await _build_list_layout()
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Grouped paginated select nodes (on message 2) -------------------------

    async def _show_grouped_paginated_select(
        self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None,
    ):
        """Render a grouped_paginated_select PanelNode on message 2.

        Two-step picker: pick a group, then pick an item within it (the item step
        is paginated via build_paginated_list_view). Picking an item auto-saves it
        through the normal get_values/set_values leaf contract and returns to the
        parent menu so the overview reflects the new value.
        """
        page_size = max(1, node.list_page_size)
        state: dict = {"region": None, "page": 0}
        is_premium = await self._is_premium(guild.id)

        async def _build_region_layout() -> discord.ui.LayoutView:
            regions = list(node.group_get_groups()) if node.group_get_groups else []
            saved: list = []
            if node.get_values:
                try:
                    saved = list(await node.get_values(guild.id))
                except Exception:
                    saved = []
            current_label = _child_summary(node, saved, guild) if saved else ""
            return build_grouped_region_view(
                node, regions, current_label,
                on_region_pick, on_region_back, back_label, is_premium=is_premium,
            )

        async def _build_items_layout() -> discord.ui.LayoutView:
            try:
                items = list(node.group_get_items(state["region"])) if node.group_get_items else []
            except Exception as e:
                logger.exception(f"Failed to load group items for {node.key}: {e}")
                items = []
            total = len(items)
            total_pages = max(1, (total + page_size - 1) // page_size)
            state["page"] = max(0, min(state["page"], total_pages - 1))
            start = state["page"] * page_size
            page_items = items[start:start + page_size]
            return build_paginated_list_view(
                node, page_items, state["page"], total, guild,
                on_item_prev, on_item_next, on_item_pick, on_item_back,
                back_label="Back", is_premium=is_premium,
            )

        async def on_region_pick(pick_interaction: discord.Interaction, region: str):
            state["region"] = region
            state["page"] = 0
            await pick_interaction.response.edit_message(view=self._rebind_session_view(session, await _build_items_layout()))

        async def on_region_back(back_interaction: discord.Interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node, edit=True,
                    refresh_parent=refresh_parent, session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        async def on_item_prev(prev_interaction: discord.Interaction):
            state["page"] = max(0, state["page"] - 1)
            await prev_interaction.response.edit_message(view=self._rebind_session_view(session, await _build_items_layout()))

        async def on_item_next(next_interaction: discord.Interaction):
            state["page"] += 1
            await next_interaction.response.edit_message(view=self._rebind_session_view(session, await _build_items_layout()))

        async def on_item_back(back_interaction: discord.Interaction):
            # Back from the item step returns to the group-picker step.
            state["region"] = None
            state["page"] = 0
            await back_interaction.response.edit_message(view=self._rebind_session_view(session, await _build_region_layout()))

        async def on_item_pick(pick_interaction: discord.Interaction, value: str):
            if not self._check_cooldown(pick_interaction.user.id, node.key, guild.id):
                await pick_interaction.response.send_message(
                    view=build_notice_layout("Slow Down", "Saving too quickly - please wait a moment."),
                    ephemeral=True,
                )
                return
            await pick_interaction.response.defer(ephemeral=True)
            old_vals = list(await node.get_values(guild.id)) if node.get_values else []
            try:
                success = await node.set_values(guild.id, [value])
            except Exception as e:
                logger.exception(f"grouped_paginated_select save failed for {node.key} ({value}): {e}")
                success = False

            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {pick_interaction.user} updated {node.key} in guild {guild.id}")
                await self._audit(
                    pick_interaction, guild.id, node,
                    old_value=old_vals, new_value=[value],
                    action="set", parent_node=parent_node,
                )
                # Return to the parent menu so the overview reflects the new value.
                if parent_node:
                    await self._navigate_to(
                        pick_interaction, parent_node, guild,
                        parent_node=grandparent_node, edit=True,
                        refresh_parent=refresh_parent, session=session,
                    )
                else:
                    try:
                        await pick_interaction.edit_original_response(view=self._rebind_session_view(session, await _build_region_layout()))
                    except discord.HTTPException as e:
                        # Best-effort UI refresh: the original response may be gone/expired.
                        logger.debug(
                            "Skipping grouped region refresh for %s in guild %s due to HTTPException: %s",
                            node.key,
                            guild.id,
                            e,
                        )
                if refresh_parent:
                    await refresh_parent()
            else:
                await pick_interaction.followup.send(
                    view=build_notice_layout("Failed to save", f"Failed to save **{node.label}**."),
                    ephemeral=True,
                )

        layout = await _build_region_layout()
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Inline modal (child of menu) ------------------------------------------

    async def _handle_inline_modal(
        self, sel_interaction, child, parent_menu, guild, summary_map, on_select, on_cancel,
        *, refresh_parent: Callable[[], Awaitable[None]] | None = None, session=None,
    ):
        """Handle a modal_input child selected from a menu dropdown."""
        current_str = ""
        if child.get_values:
            try:
                vals = list(await child.get_values(guild.id))
                current_str = str(vals[0]) if vals else ""
            except Exception:
                pass  # Non-critical; modal works without pre-filled value

        async def on_modal_submit(modal_interaction: discord.Interaction, raw_value: str):
            # Empty → clear
            if not raw_value and child.clear_values:
                if not self._check_cooldown(sel_interaction.user.id, child.key, guild.id):
                    await modal_interaction.response.send_message(
                        view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                        ephemeral=True,
                    )
                    return
                await modal_interaction.response.defer(ephemeral=True)
                old_vals = list(await child.get_values(guild.id)) if child.get_values else []
                success = await child.clear_values(guild.id)
                if success:
                    await self._audit(
                        modal_interaction, guild.id, child,
                        old_value=old_vals, new_value=[],
                        action="clear", parent_node=parent_menu,
                    )
            else:
                # Validate
                if child.modal_validator:
                    ok, value, error = child.modal_validator(raw_value)
                    if not ok:
                        # Discord forbids responding to a MODAL_SUBMIT interaction with
                        # another modal, so surface the error as an ephemeral notice and
                        # let the user re-open the field from the menu to try again.
                        await modal_interaction.response.send_message(
                            view=build_notice_layout("Invalid Input", error or "Please try again."),
                            ephemeral=True,
                        )
                        return
                else:
                    value = raw_value

                if not self._check_cooldown(sel_interaction.user.id, child.key, guild.id):
                    await modal_interaction.response.send_message(
                        view=build_notice_layout("Slow Down", "Saving too quickly, please wait a moment."),
                        ephemeral=True,
                    )
                    return
                await modal_interaction.response.defer(ephemeral=True)
                old_vals = list(await child.get_values(guild.id)) if child.get_values else []
                try:
                    success = await child.set_values(guild.id, [value])
                except Exception as save_exc:
                    logger.exception("Inline modal save failed for %s", child.key)
                    await modal_interaction.followup.send(
                        view=build_notice_layout(
                            "Failed to save",
                            f"Could not save **{child.label}**. {save_exc.__class__.__name__}",
                        ),
                        ephemeral=True,
                    )
                    return
                if success:
                    await self._audit(
                        modal_interaction, guild.id, child,
                        old_value=old_vals, new_value=[value],
                        action="set", parent_node=parent_menu,
                    )

            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {sel_interaction.user} updated {child.key} in guild {guild.id}")
                # Refresh parent menu view
                new_summary = await self._gather_summaries(parent_menu, guild.id)
                locked = await self._compute_locked_keys(parent_menu, guild.id)
                new_layout = build_menu_view(parent_menu, new_summary, on_select, on_cancel, locked, guild_id=guild.id, guild=guild, is_premium=await self._is_premium(guild.id))
                try:
                    await sel_interaction.edit_original_response(view=self._rebind_session_view(session, new_layout))
                except discord.HTTPException as http_exc:
                    logger.warning("Could not refresh inline-modal parent menu: %s", http_exc)
                # Refresh message 1 navigation if needed
                if refresh_parent:
                    await refresh_parent()
            else:
                await modal_interaction.followup.send(
                    view=build_notice_layout(
                        "Failed to update", f"Could not update **{child.label}**.",
                    ),
                    ephemeral=True,
                )

        modal = PanelInputModal(
            title=child.modal_title or f"Set {child.label}",
            label=child.modal_label or child.label,
            placeholder=child.modal_placeholder or "",
            min_length=child.modal_min_length,
            max_length=child.modal_max_length,
            default=current_str,
            on_submit_callback=on_modal_submit,
            paragraph=child.modal_paragraph,
            required=child.modal_required,
        )
        await sel_interaction.response.send_modal(modal)

    # -- Summary & Lock Computation --------------------------------------------

    async def _gather_deep_summaries(
        self, root: PanelNode, guild_id: int, guild: discord.Guild,
    ) -> dict[str, dict[str, str | dict[str, str]]]:
        """Gather human-readable summaries for every leaf node across all categories.

        Returns {cat_key: {child_key: summary_str | {sub_key: summary_str}}}
        Used by the overview (message 1) to show full server config detail.
        """
        result: dict[str, dict[str, str | dict[str, str]]] = {}
        for cat_key, cat_node in root.children.items():
            cat_data: dict[str, str | dict[str, str]] = {}
            # A childless top-level node (a direct leaf or action on the root)
            # has no children to summarize - summarize the node ITSELF under
            # the "__self__" sentinel so the overview can show its state
            # instead of a bare label. Honors summary_builder via _leaf_summary.
            if not cat_node.children and cat_node.kind != "menu":
                summary = await self._leaf_summary(cat_node, guild_id, guild)
                if summary and summary != "Not configured":
                    cat_data["__self__"] = summary
                result[cat_key] = cat_data
                continue
            for child_key, child_node in cat_node.children.items():
                if child_node.kind == "menu":
                    # Pure feature-toggle menu (a switch with no sub-settings):
                    # report its on/off state, never "Not configured".
                    if child_node.toggle_get and not child_node.children:
                        try:
                            enabled = await child_node.toggle_get(guild_id)
                        except Exception:
                            enabled = None
                        cat_data[child_key] = (
                            ("Enabled" if enabled else "Disabled")
                            if enabled is not None
                            else "Not configured"
                        )
                        continue
                    # Sub-menu: gather each sub-child
                    sub_data: dict[str, str] = {}
                    for sub_key, sub_node in child_node.children.items():
                        sub_data[sub_key] = await self._leaf_summary(sub_node, guild_id, guild)
                    cat_data[child_key] = sub_data
                else:
                    cat_data[child_key] = await self._leaf_summary(child_node, guild_id, guild)
            result[cat_key] = cat_data
        return result

    async def _leaf_summary(
        self, node: PanelNode, guild_id: int, guild: discord.Guild,
    ) -> str:
        """Produce a guild-aware summary string for a single leaf node."""
        # A custom summary_builder wins here as it does in _gather_summaries, so the
        # overview (message 1) and the category menu (message 2) describe a node the
        # same way. This also decides "configured" for the category badge, which tests
        # the returned string against _UNSET_SUMMARIES - so a node whose value is not
        # renderable by the generic branches below (a bespoke action editor) needs its
        # builder honored here or it reads as unset no matter how it is configured.
        if node.summary_builder:
            try:
                text = await node.summary_builder(guild_id)
            except Exception:
                text = None
            if text is not None:
                return text

        if node.kind == "paginated_list":
            count = await self._paginated_list_count(node, guild_id)
            return f"{count} item(s)" if count else "Empty"

        if node.kind == "dict_editor" and node.dict_get_values:
            # Dict editors have dict_get_values, not get_values - without this
            # branch they read "Not configured" forever regardless of content.
            try:
                entries = await node.dict_get_values(guild_id) or {}
            except Exception:
                entries = {}
            n = len(entries)
            return f"{n} entr{'y' if n == 1 else 'ies'}" if n else "Not set"

        if not node.get_values:
            return "Not configured"
        try:
            vals = list(await node.get_values(guild_id))
        except Exception:
            return "Not configured"

        if not vals:
            if node.kind == "role_select":
                return "Not assigned"
            return "Not set"

        if node.kind == "channel_select":
            names = []
            for cid in vals:
                ch = guild.get_channel(int(cid))
                names.append(ch.mention if ch else f"Unknown ({cid})")
            return ", ".join(names)

        if node.kind == "role_select":
            names = []
            for rid in vals:
                role = guild.get_role(int(rid))
                names.append(f"@{role.name}" if role else f"Unknown ({rid})")
            return ", ".join(names)

        if node.kind == "option_select":
            default_val = _get_default_option_value(node)
            label = _option_label(node, str(vals[0]))
            if default_val is not None and str(vals[0]) == default_val:
                return f"{label} (Default)"
            return label

        if node.kind in ("modal_input", "dual_modal_input"):
            return str(vals[0]) if vals[0] else "Not set"

        return _child_summary(node, vals)

    async def _gather_toggle_states(
        self, root: PanelNode, guild_id: int,
    ) -> dict[str, bool | None]:
        """Collect toggle states for all categories."""
        states: dict[str, bool | None] = {}
        for key, child in root.children.items():
            if child.toggle_get:
                states[key] = await child.toggle_get(guild_id)
            else:
                states[key] = None
        return states

    async def _gather_summaries(self, node: PanelNode, guild_id: int) -> dict[str, list]:
        """Fetch current values for all children of a menu node."""
        summary_map: dict[str, list] = {}
        for key, child in node.children.items():
            # Custom overview summary: precompute the text and carry it through
            # the summary map behind a sentinel _child_summary renders verbatim.
            if child.summary_builder:
                try:
                    text = await child.summary_builder(guild_id)
                except Exception:
                    text = None
                if text is not None:
                    summary_map[key] = [f"__summary__:{text}"]
                    continue
            if child.kind == "paginated_list":
                count = await self._paginated_list_count(child, guild_id)
                summary_map[key] = ["x"] * count
                continue
            if child.kind == "dict_editor" and child.dict_get_values:
                # Dict editors expose dict_get_values, not get_values - without
                # this branch the menu row reads "Not configured" forever.
                try:
                    entries = await child.dict_get_values(guild_id) or {}
                except Exception:
                    entries = {}
                n = len(entries)
                text = f"{n} entr{'y' if n == 1 else 'ies'}" if n else "Not set"
                summary_map[key] = [f"__summary__:{text}"]
                continue
            if child.get_values:
                try:
                    summary_map[key] = list(await child.get_values(guild_id))
                except Exception:
                    summary_map[key] = []
            elif child.kind == "menu":
                # A menu that exists purely to host a feature toggle (no
                # sub-settings) is summarized by its on/off state, never
                # "Not configured" - a toggle is always enabled or disabled.
                if child.toggle_get and not child.children:
                    try:
                        enabled = await child.toggle_get(guild_id)
                    except Exception:
                        enabled = None
                    if enabled is not None:
                        summary_map[key] = ["__toggle_on__" if enabled else "__toggle_off__"]
                        continue
                # Recursively check sub-children to count customized settings
                customized = []
                has_stored_value = False
                for sub_key, sub_child in child.children.items():
                    if not sub_child.get_values:
                        continue
                    try:
                        vals = list(await sub_child.get_values(guild_id))
                    except Exception:
                        continue
                    if not vals:
                        continue
                    has_stored_value = True
                    if sub_child.kind == "option_select":
                        default_val = _get_default_option_value(sub_child)
                        if default_val is not None and len(vals) == 1 and str(vals[0]) == default_val:
                            continue  # still default, don't count as customized
                    customized.append(sub_key)

                # Single-child menus: show the value label directly
                if len(child.children) == 1:
                    only_child = next(iter(child.children.values()))
                    if only_child.kind == "option_select" and only_child.get_values:
                        try:
                            vals = list(await only_child.get_values(guild_id))
                        except Exception:
                            vals = []
                        if vals:
                            label = _option_label(only_child, str(vals[0]))
                            default_val = _get_default_option_value(only_child)
                            if default_val is not None and str(vals[0]) == default_val:
                                summary_map[key] = [f"Default ({label})"]
                            else:
                                summary_map[key] = [label]
                            continue

                if customized:
                    summary_map[key] = customized
                elif has_stored_value:
                    # All stored values match defaults - mark as configured
                    summary_map[key] = ["__defaults__"]
                else:
                    summary_map[key] = []
            else:
                summary_map[key] = []
        return summary_map

    @staticmethod
    async def _paginated_list_count(node: PanelNode, guild_id: int) -> int:
        """Item count for a paginated_list node (efficient list_count, else len)."""
        try:
            if node.list_count is not None:
                return int(await node.list_count(guild_id))
            if node.list_get_items is not None:
                return len(list(await node.list_get_items(guild_id)))
        except Exception:
            return 0
        return 0

    async def _compute_locked_keys(self, node: PanelNode, guild_id: int) -> set[str]:
        """Compute which children of a menu node should be locked."""
        if node.locked_children:
            return await node.locked_children(guild_id)
        return set()

    # -- Helpers ---------------------------------------------------------------

    def _rebind_session_view(self, session, view):
        """Re-bind a freshly rebuilt panel view to the PanelSession, and reset the
        shared idle timer. A newly built LayoutView otherwise keeps discord's default
        300s timeout and an unwrapped interaction_check, so after any in-place rebuild
        the author lock is lost and the view expires on its own 300s clock instead of
        the session's. Returns the (now registered) view so it can be wrapped inline
        around an ``edit(view=...)`` call. No-op when there is no active session."""
        if session is not None:
            session.register_view(view)
            session.touch()
        return view

    def _check_cooldown(self, user_id: int, node_key: str, guild_id: int = None) -> bool:
        """Check and set autosave cooldown. Returns True if allowed.

        Scoped by ``(guild_id, user_id, node_key)`` so the same user acting on the
        same node in two different guilds does not share one cooldown window."""
        rl_key = (guild_id, user_id, node_key)
        now = time.monotonic()
        if now - self._autosave_cooldowns.get(rl_key, 0.0) < self.AUTOSAVE_COOLDOWN:
            return False
        self._autosave_cooldowns[rl_key] = now
        # Prune stale entries
        cutoff = now - 60.0
        self._autosave_cooldowns = {
            k: v for k, v in self._autosave_cooldowns.items() if v > cutoff
        }
        return True

    async def _send_or_edit(
        self,
        interaction: discord.Interaction,
        layout: discord.ui.LayoutView,
        edit: bool,
    ) -> None:
        """Send a new followup message (message 2) or edit the current one."""
        try:
            if interaction.response.is_done():
                if edit:
                    await interaction.edit_original_response(view=layout)
                else:
                    await interaction.followup.send(view=layout, ephemeral=True)
            elif edit:
                await interaction.response.edit_message(view=layout)
            else:
                await interaction.response.send_message(view=layout, ephemeral=True)
        except discord.HTTPException as http_exc:
            logger.warning("Could not send/edit msg2 layout: %s", http_exc)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
    logger.info("AdminCog loaded")
