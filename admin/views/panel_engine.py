# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""
Admin Panel Engine -Generic config-driven panel builder.

Defines PanelNode dataclass and generic view builders (build_menu_view,
build_select_view, build_modal_trigger_view) so new admin panels can be
added as pure config trees without writing custom view builder code.
"""

from __future__ import annotations

import discord
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

from .base import (
    AdminLayoutBuilder,
    cid,
    create_empty_layout,
    readonly_container,
    editable_container,
    notice_container,
)


@dataclass
class PanelNode:
    """A node in the admin panel config tree.

    Attributes:
        key:          Unique identifier; also used as rate-limit cooldown key.
        label:        Display label for headers and dropdown options.
        kind:         Node type: "menu" | "role_select" | "channel_select" | "option_select"
                      | "modal_input" | "dual_modal_input" | "file_upload" | "dict_editor"
                      | "paginated_list" | "grouped_paginated_select" | "action"
        description:  Short description shown in the parent dropdown and as
                      instruction text on the select view.
        blurb:        Optional one-line stand-in for `description` on the
                      DASHBOARD dropdown only. Top-level descriptions render
                      verbatim as option descriptions, which Discord caps at
                      100 chars; when a top-level node's body text is
                      legitimately longer, set a blurb that fits instead of
                      gutting the description. validate_panel enforces that
                      whichever of the two the dropdown uses is within the cap.

        children:     (menu only) Ordered dict of child_key -> PanelNode.
        get_values:   async (guild_id) -> list  -returns the current selection.
        set_values:   async (guild_id, values) -> bool  -persists new selection.
        clear_values: Optional async (guild_id) -> bool  -enables a Clear button.
        pre_check:    Optional async (interaction, guild_id) -> LayoutView|None; None=allow.
        post_save_hook: Optional async (interaction, guild_id, saved_values) -> None.
        options:      (option_select only) list of (value, label) or
                      (value, label, description) tuples.
        min_values:   Minimum number of selections (default 1).
        max_values:   Maximum number of selections (default 25).

        locked_children: (menu only) async (guild_id) -> set[str] of child keys to lock.
        lock_reason:  Message shown when a locked child is clicked.
        toggle_get:   (menu only) async (guild_id) -> bool -current enabled state.
        toggle_set:   (menu only) async (guild_id, enabled: bool) -> bool -set state.
    """

    key: str
    label: str
    kind: str  # "menu" | "role_select" | "channel_select" | "option_select" | "modal_input" | "dual_modal_input" | "file_upload" | "dict_editor" | "paginated_list" | "grouped_paginated_select" | "action"
    description: str = ""
    blurb: Optional[str] = None

    # menu nodes only
    children: dict[str, "PanelNode"] = field(default_factory=dict)

    # menu lock / toggle support
    locked_children: Optional[Callable] = None  # async (guild_id) -> set[str]
    lock_reason: str = ""
    toggle_get: Optional[Callable] = None       # async (guild_id) -> bool
    toggle_set: Optional[Callable] = None       # async (guild_id, bool) -> bool
    on_toggle_callback: Optional[Callable] = None  # async (guild, enabled: bool) -> None
    description_builder: Optional[Callable] = None  # sync (guild_id) -> str; overrides static description at render time

    # select / modal_input nodes
    get_values: Optional[Callable] = None   # async (guild_id) -> list[int | str]
    set_values: Optional[Callable] = None   # async (guild_id, values) -> bool
    clear_values: Optional[Callable] = None  # async (guild_id) -> bool
    pre_check: Optional[Callable] = None       # async (interaction, guild_id) -> LayoutView|None
    post_save_hook: Optional[Callable] = None  # async (interaction, guild_id, saved_values) -> None
    # role/channel/option_select only - optional async (guild, values) -> error_str | None,
    # run on save (after permission checks, before set_values). Return an error string to
    # reject the selection with a notice; None to allow. For validating a selection against
    # live guild state (e.g. "this channel must sit inside the configured category").
    value_validator: Optional[Callable] = None

    # channel_select only
    channel_types: Optional[list] = None   # list[discord.ChannelType] to filter

    # role_select / channel_select only - the inline create button (standard §11).
    # Every role/channel select editor carries a create button by default;
    # allow_create=False opts a node out. create_entity, when set, replaces the
    # engine's default create-and-save: async (guild, name, actor) ->
    # (entity | None, error_str | None), and OWNS persistence (the engine skips
    # set_values; use it for flows that configure beyond storing the id).
    # create_label overrides the button label ("Create Role" / "Create Channel" /
    # "Create Category" / "Create Voice Channel" by default).
    allow_create: bool = True
    create_entity: Optional[Callable] = None
    create_label: str = ""

    # option_select only
    options: Optional[list] = None          # [(val, label[, desc]), ...]
    min_values: int = 1
    max_values: int = 25

    # premium gating
    premium_values: set[str] | None = None  # option values that require premium
    premium_max_values: int | None = None   # max_values override for premium guilds

    # modal_input only
    modal_title: str = ""
    modal_label: str = "Value"
    modal_placeholder: str = ""
    modal_min_length: int = 1
    modal_max_length: int = 100
    modal_validator: Optional[Callable] = None  # (str) -> (bool, converted_value, error_msg)
    modal_paragraph: bool = False
    modal_required: bool = True

    # dual_modal_input -second field
    modal_label_2: str = ""
    modal_placeholder_2: str = ""
    modal_min_length_2: int = 0
    modal_max_length_2: int = 500

    # dict_editor only
    # dict_get_values: async (guild_id) -> dict[str, Any]  current entries.
    # dict_set_value:  async (guild_id, key, value) -> bool  add/update one entry.
    # dict_remove_value: async (guild_id, key) -> bool  delete one entry.
    # dict_key_label / dict_value_label: TextInput labels for the add/edit modal.
    # dict_value_validator: sync (raw_str) -> (ok, error_msg, parsed_value).
    # dict_key_validator: same contract, applied to the KEY on every path (the
    #   dual modal, the channel-key flow, and the key modal of the role-value
    #   flow). When it returns a parsed value that is not None, the key is stored
    #   as ``str(parsed)`` so a typed key ("05" -> 5 -> "5") is normalized before
    #   it reaches storage. Unset (the default) means keys are only checked for
    #   emptiness, exactly as before.
    # dict_max_entries: optional cap on the number of entries.
    dict_get_values: Optional[Callable] = None
    dict_set_value: Optional[Callable] = None
    dict_remove_value: Optional[Callable] = None
    dict_key_label: str = "Key"
    dict_value_label: str = "Value"
    dict_value_validator: Optional[Callable] = None
    dict_key_validator: Optional[Callable] = None
    dict_max_entries: Optional[int] = None

    # dict_editor input shapes. Both default to "text", which is the original
    # dual-field-modal editor - a node that sets neither renders and behaves
    # exactly as it always has.
    #
    # dict_key_kind:
    #   "text"    - key typed into the modal (default).
    #   "channel" - key picked from a native ChannelSelect and stored as
    #               str(channel.id), so admins never type a snowflake. Add becomes
    #               "pick a channel -> supply the value"; Edit keeps the key fixed
    #               (change a channel key by removing the entry and adding it again).
    # dict_key_channel_types: list[discord.ChannelType] filtering that ChannelSelect
    #   (None = every channel type). Only read when dict_key_kind == "channel".
    # dict_value_kind:
    #   "text" - value typed into the modal (default), parsed by dict_value_validator.
    #   "role" - value picked from a native RoleSelect and stored as str(role.id).
    #            Role values are permission-checked before they are persisted (the
    #            bot needs Manage Roles, the role must exist, must not be @everyone,
    #            must not be integration-managed, and must sit below the bot's top
    #            role) and skip dict_value_validator, which has no meaning for a
    #            snowflake.
    dict_key_kind: str = "text"            # "text" | "channel"
    dict_key_channel_types: Optional[list] = None   # list[discord.ChannelType]
    dict_value_kind: str = "text"          # "text" | "role"

    # file_upload only
    # template_data: sync (no args) -> (bytes, filename); when set, renders a
    #   "Download Template" button beside Upload so users can grab a starter file.
    template_data: Optional[Callable] = None

    # Discord permission requirements (validated by permission_checks.py).
    # required_channel_perms: discord.Permissions attribute names the bot must
    #   hold inside any channel selected through this node (channel_select).
    # requires_role_manage: when True, the bot must hold manage_roles globally
    #   AND outrank every role assigned through this node (role_select).
    required_channel_perms: list[str] | None = None
    requires_role_manage: bool = False

    # Dashboard grouping for top-level children (see ADMIN_PANEL_STANDARD.md §7).
    # "main" renders above the disabled "── Feature Configurations ──" divider in
    # the dashboard category Select; "feature" renders below.
    category_group: str = "main"

    # Audit section override. Audit entries normally take their section from the
    # parent menu's key, falling back to the leaf's own key when it sits at the
    # root. Set this when a leaf is promoted to the root (a wrapper menu with one
    # child was removed) so its history keeps the section it always had instead
    # of splitting the dashboard's audit filter across two names.
    audit_section: Optional[str] = None

    # Tier-aware label override. When the active guild has premium and
    # premium_label is set, renderers display it instead of `label`.
    premium_label: Optional[str] = None

    # file_upload only - optional sync (parsed) -> (ok, error_msg) validator. The
    # engine reads the attachment, decodes it as UTF-8 text, and (when this is set)
    # parses it as JSON and runs the validator against the PARSED payload before
    # persisting. set_values receives the decoded text (str), never the raw
    # discord.Attachment. Uploads are text/JSON only; binary payloads are out of
    # contract.
    schema_validator: Optional[Callable] = None

    # paginated_list only - a generic, scrollable list of items with an optional
    # per-item action. The engine paginates: each page shows up to
    # ``list_page_size`` items, so the per-item action Select never exceeds
    # Discord's 25-option cap regardless of total list length.
    list_get_items: Optional[Callable] = None          # async (guild_id) -> list[Any]; full list
    list_format_line: Optional[Callable] = None        # sync (item, abs_index) -> str; display line
    list_item_value: Optional[Callable] = None         # sync (item) -> str; stable id for the action select
    list_item_option_label: Optional[Callable] = None  # sync (item, abs_index) -> str; <=100-char select label
    list_page_size: int = 10                           # items per page (must be <= 25)
    list_action_label: Optional[str] = None            # e.g. "Delete"; None => browse-only
    list_action: Optional[Callable] = None             # async (guild_id, value) -> bool; act on chosen item
    list_action_confirm_line: Optional[Callable] = None  # sync (item) -> str; confirm-step text
    list_count: Optional[Callable] = None              # async (guild_id) -> int; efficient summary count

    # grouped_paginated_select only - a single-value leaf chosen via a two-step
    # picker: pick a group, then pick an item within it (the item step reuses the
    # list_* formatter fields above + build_paginated_list_view). get_values /
    # set_values keep the normal single-value leaf contract.
    group_get_groups: Optional[Callable] = None        # sync () -> list[(group_value, group_label)]
    group_get_items: Optional[Callable] = None         # sync (group_value) -> list[item]

    # action only - a leaf that runs an arbitrary handler (no value contract).
    on_run: Optional[Callable] = None                  # async (interaction, ctx) -> None

    # Dashboard summary overrides (consumed by some overview renderers).
    view_only: bool = False
    default_summary: str = ""
    is_customized: Optional[Callable] = None

    # Optional custom overview summary: async ``(guild_id) -> str`` replacing the
    # generic value summary for this node on menu overviews. Precomputed by
    # ``AdminCog._gather_summaries`` and carried through the summary map behind a
    # sentinel value; ``_child_summary`` renders it verbatim. (Merged up from
    # EcomRebuild's seam, its first consumer.)
    summary_builder: Optional[Callable] = None

    # Async description override: async (guild) -> str, resolved at render time.
    async_description: Optional[Callable] = None

    # Opt-in override for progress counting (the "N of M configured" category badge).
    # None = infer from ``kind`` (see ``_counts_toward_progress``), which is right for
    # every node whose kind already implies whether it holds a value.
    #
    # Set True on a ``kind="action"`` node that is really a bespoke SETTINGS EDITOR
    # owning stored config (codex's Color Tiers / Tag Tracker / Boost Tracker / Drops
    # Channel / Tracked Channels), so it is counted like any other setting. Such a node
    # should also supply ``get_values`` (so "configured" can be determined) and normally
    # ``summary_builder`` (so the summary line reads as text rather than blank).
    #
    # Leave unset on the stateless one-shot actions the kind was designed for - View
    # Status, Export, Publish, Reset, Purge, premium activation - which have no stored
    # value and must not inflate the badge. Set False to force-exclude any node.
    counts_as_setting: Optional[bool] = None


@dataclass
class ActionContext:
    """Context handed to an ``action``-kind node's handler.

    The engine dispatches ``kind="action"`` nodes to ``node.on_run(cog, interaction,
    guild, ctx)``. ``ctx`` carries everything a bot-specific handler needs to render
    into the shared Message-2 surface and chain back-navigation, without the engine
    knowing the handler's internals:

        session:          the active PanelSession (synced timeout / msg2 tracking)
        parent_node:      the menu this action was opened from (for Back), or None
        grandparent_node: the parent's parent (for multi-level Back chains)
        edit:             True to replace the current msg2; False to open a fresh one
        refresh_parent:   async () -> None; refresh the overview (msg1) after a change
        is_premium:       whether the guild has premium (already resolved)
        back_label:       "Back" / "Close" per the §1 navigation table
    """
    session: Optional[object] = None
    parent_node: Optional["PanelNode"] = None
    grandparent_node: Optional["PanelNode"] = None
    edit: bool = False
    refresh_parent: Optional[Callable] = None
    is_premium: bool = False
    back_label: str = "Back"


# -- Helpers -------------------------------------------------------------------

DASHBOARD_FEATURE_SEPARATOR_VALUE = "__feature_sep__"


def _effective_label(node: "PanelNode", is_premium: bool) -> str:
    """Return premium_label when the guild has premium and one is defined; else label."""
    if is_premium and node.premium_label:
        return node.premium_label
    return node.label


def _get_default_option_value(node: PanelNode) -> str | None:
    """Get the default value from an option_select node by scanning for '(Default)' in labels."""
    if not node.options:
        return None
    for opt in node.options:
        if "(Default)" in opt[1]:
            return str(opt[0])
    return None


def _option_label(node: PanelNode, value: str) -> str:
    """Look up the human-readable label for an option value, stripping '(Default)' suffix."""
    if not node.options:
        return value
    for opt in node.options:
        if str(opt[0]) == value:
            return opt[1].replace(" (Default)", "").replace(" (Premium)", "").replace("💎 ", "").strip()
    return value


# Discord's hard cap on a select option's label and description. Exceeding it
# is not cosmetic: Discord rejects the whole message with a 50035 Invalid Form
# Body, so nothing over this length may ever reach a SelectOption. Authored
# text is validated against it at startup (validate_panel) so violations get
# REWRITTEN in source; dynamic summaries are rewritten to a compact form at
# render time (_option_summary). Nothing is clipped mid-string.
OPTION_TEXT_LIMIT = 100


def validate_panel(root: PanelNode) -> None:
    """Reject authored panel text that Discord would refuse at render time.

    Called from AdminCog.__init__ so a bot whose panel config carries an
    over-limit string fails loudly at startup, naming every offender - the
    text must be rewritten to fit, never silently truncated. Only static,
    authored fields are checked; dynamic summaries stay within limits via
    _option_summary's compact rewrites.

    Checks:
    * every node's label and premium_label (rendered as a select option label
      in the dashboard and group menus; 4 chars of headroom are reserved for
      the lock/premium emoji prefixes added at render time);
    * every node's blurb (its whole purpose is fitting the option cap);
    * the ROOT'S DIRECT CHILDREN's dashboard dropdown text - the blurb, or the
      description when no blurb is set (deeper descriptions are menu body text
      with no such cap: give an over-long top-level node a blurb rather than
      gutting its body text);
    * every option_select entry's label (same emoji headroom) and description.
    """
    problems: list[str] = []
    label_limit = OPTION_TEXT_LIMIT - 4

    def _check(text, where: str, limit: int) -> None:
        if text and len(text) > limit:
            problems.append(f"{where} is {len(text)} chars (limit {limit})")

    def _walk(node: PanelNode, path: str, is_top_level: bool) -> None:
        _check(node.label, f"{path}: label", label_limit)
        _check(getattr(node, "premium_label", None), f"{path}: premium_label", label_limit)
        _check(node.blurb, f"{path}: blurb", OPTION_TEXT_LIMIT)
        if is_top_level and not node.blurb:
            _check(
                node.description,
                f"{path}: description (dashboard select option; set a blurb "
                "or shorten it)",
                OPTION_TEXT_LIMIT,
            )
        for opt in (node.options or []):
            _check(opt[1], f"{path}: option {opt[0]!r} label", label_limit)
            if len(opt) > 2:
                _check(opt[2], f"{path}: option {opt[0]!r} description", OPTION_TEXT_LIMIT)
        for key, child in (node.children or {}).items():
            _walk(child, f"{path}.{key}", False)

    for key, child in (root.children or {}).items():
        _walk(child, key, True)

    if problems:
        raise ValueError(
            "Panel config contains text Discord will reject; rewrite it to fit:\n- "
            + "\n- ".join(problems)
        )


def _option_summary(node: PanelNode, values: list, guild: discord.Guild | None) -> str:
    """A child summary safe to use as a select-option description.

    The full summary (which may join arbitrary role/channel names) already
    appears in the menu body above the dropdown, so when it exceeds Discord's
    cap the dropdown line is REWRITTEN to a progressively more compact form
    rather than clipped: full summary -> guild-independent count form
    ("3 role(s) assigned") -> a generic pointer at the body text.
    """
    full = _child_summary(node, values, guild)
    if len(full) <= OPTION_TEXT_LIMIT:
        return full
    compact = _child_summary(node, values, None)
    if len(compact) <= OPTION_TEXT_LIMIT:
        return compact
    return "Configured - see the summary above"


def _child_summary(node: PanelNode, values: list, guild: discord.Guild | None = None) -> str:
    """Return a short human-readable summary of a child node's current value."""
    # A node with a summary_builder had its text precomputed in _gather_summaries
    # and carried through the summary map behind this sentinel - render verbatim.
    if (
        len(values) == 1
        and isinstance(values[0], str)
        and values[0].startswith("__summary__:")
    ):
        return values[0][len("__summary__:"):]
    kind = node.kind
    n = len(values)
    if kind == "role_select":
        if not n:
            return "Not assigned"
        if guild is None:
            return f"{n} role(s) assigned"
        names = []
        for rid in values:
            role = guild.get_role(int(rid))
            names.append(f"@{role.name}" if role is not None else f"Unknown ({rid})")
        return ", ".join(names)
    if kind == "channel_select":
        is_category_only = (
            node.channel_types is not None
            and len(node.channel_types) == 1
            and node.channel_types[0] == discord.ChannelType.category
        )
        noun = "category" if is_category_only else "channel"
        if not n:
            return "Not set"
        if guild is None:
            return f"{noun.capitalize()} configured"
        names = []
        for cid in values:
            ch = guild.get_channel(int(cid))
            if ch is None:
                names.append(f"Unknown ({cid})")
            elif is_category_only:
                names.append(ch.name)
            else:
                names.append(f"#{ch.name}")
        return ", ".join(names)
    if kind == "option_select":
        if not n:
            return "Not set"
        default_val = _get_default_option_value(node)
        if n == 1 and default_val is not None and str(values[0]) == default_val:
            return "Default"
        label = _option_label(node, str(values[0])) if n == 1 else f"{n} selected"
        return label
    if kind == "modal_input":
        return str(values[0]) if values else "Not set"
    if kind == "dual_modal_input":
        val1 = values[0] if len(values) > 0 else ""
        return str(val1) if val1 else "Not set"
    if kind == "menu":
        # Feature-toggle menu (a menu whose only purpose is an on/off switch):
        # always report its state, never "Not configured".
        if n == 1 and values[0] in ("__toggle_on__", "__toggle_off__"):
            return "Enabled" if values[0] == "__toggle_on__" else "Disabled"
        # Single-child menus pass a pre-formatted display string
        if n == 1 and len(node.children) == 1:
            return str(values[0])
        if n:
            # Sentinel for "all values stored but all match defaults"
            if n == 1 and values[0] == "__defaults__":
                return "Default settings"
            return f"{n} setting(s) customized"
        return "Not configured"
    if kind == "paginated_list":
        return f"{n} item(s)" if n else "Empty"
    if kind == "grouped_paginated_select":
        return str(values[0]) if values else "Not set"
    if kind == "action":
        return ""
    return f"{n} configured" if n else "Not set"


# -- Generic view builders -----------------------------------------------------

def build_menu_view(
    node: PanelNode,
    summary_map: dict[str, list],
    on_select: Callable[[discord.Interaction, str], Awaitable[None]],
    on_cancel: Callable[[discord.Interaction], Awaitable[None]],
    locked_keys: set[str] | None = None,
    toggle_state: bool | None = None,
    on_toggle: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    back_label: str = "Done",
    preamble_items: list[discord.ui.Item] | None = None,
    extra_buttons: list[discord.ui.Button] | None = None,
    description_override: str | None = None,
    guild_id: int | None = None,
    guild: discord.Guild | None = None,
    is_premium: bool = False,
    breadcrumb: str | None = None,
) -> discord.ui.LayoutView:
    """Build an overview menu view for a PanelNode with kind="menu".

    Args:
        node:            The menu PanelNode to render.
        summary_map:     Pre-fetched {child_key: current_values_list} for all children.
        on_select:       Async callback (interaction, child_key) -navigate into child.
        on_cancel:       Async callback (interaction) -close / back.
        locked_keys:     Set of child keys that should show a lock icon.
        toggle_state:    Current enabled state for the feature toggle (None = no toggle).
        on_toggle:       Async callback (interaction) -toggle enable/disable.
        back_label:      Label for the back/close button (e.g. "Back", "Close Panel", "Done").
        preamble_items:  Optional items inserted after header, before description.
        extra_buttons:   Optional buttons appended to the final ActionRow.
        breadcrumb:      Optional path string ("A > B > C") rendered under the header per §1.
    """
    builder = AdminLayoutBuilder()
    _locked = locked_keys or set()

    # Header with optional toggle status
    node_label = _effective_label(node, is_premium)
    if toggle_state is not None:
        status = "Enabled" if toggle_state else "Disabled"
        header_text = f"## {node_label} -{status}"
    else:
        header_text = f"## {node_label}"
    if breadcrumb:
        header_text = f"{header_text}\nPath: {breadcrumb}"
    builder.add_header(header_text)

    # Optional preamble (e.g. setup guide)
    if preamble_items:
        for item in preamble_items:
            builder.add_item(item)

    if description_override is not None:
        desc_text = description_override
    elif node.description_builder is not None and guild_id is not None:
        try:
            desc_text = node.description_builder(guild_id)
        except Exception:
            desc_text = node.description
    else:
        desc_text = node.description
    # Read-only block: tier-fixed / derived / non-configurable context (description).
    # This is the "what this setting does" + premium-tier breakdown.
    if desc_text:
        builder.add_item(readonly_container(discord.ui.TextDisplay(desc_text)))

    # Editable block: admin-settable child summaries.
    # Each line shows the current value of a configurable child the user can edit.
    # Children with no value summary (actions) render as a plain label - a
    # trailing colon with nothing after it reads as an unfilled placeholder.
    child_lines = []
    for key, child in node.children.items():
        prefix = "\U0001f512 " if key in _locked else ""
        child_label = _effective_label(child, is_premium)
        summary = _child_summary(child, summary_map.get(key, []), guild)
        if summary:
            child_lines.append(f"- **{prefix}{child_label}:** {summary}")
        else:
            child_lines.append(f"- **{prefix}{child_label}**")

    if child_lines or node.children:
        # Visual separator between read-only context and editable summaries.
        if desc_text:
            builder.add_separator()

        editable_items: list[discord.ui.Item] = []
        if child_lines:
            editable_items.append(discord.ui.TextDisplay("\n".join(child_lines)))
        if node.children:
            editable_items.append(discord.ui.TextDisplay(
                "Select a category below to configure it."
            ))
            options = []
            for key, child in node.children.items():
                child_label = _effective_label(child, is_premium)
                options.append(discord.SelectOption(
                    label=f"\U0001f512 {child_label}" if key in _locked else child_label,
                    value=key,
                    description=(
                        "Locked - configure prerequisite first"
                        if key in _locked
                        else _option_summary(child, summary_map.get(key, []), guild)
                    ),
                ))
            select = discord.ui.Select(
                placeholder="Select a category...",
                custom_id=cid("editor", "select", node.key),
                options=options,
            )

            async def _select_cb(interaction: discord.Interaction):
                await on_select(interaction, interaction.data["values"][0])

            select.callback = _select_cb
            select_row = discord.ui.ActionRow()
            select_row.add_item(select)
            editable_items.append(select_row)
        builder.add_item(editable_container(*editable_items))

    # Action row: optional toggle button + Done button
    row = discord.ui.ActionRow()

    if on_toggle is not None and toggle_state is not None:
        toggle_btn = discord.ui.Button(
            label="Disable" if toggle_state else "Enable",
            style=discord.ButtonStyle.danger if toggle_state else discord.ButtonStyle.success,
            custom_id=cid("editor", "toggle", node.key),
        )
        toggle_btn.callback = on_toggle
        row.add_item(toggle_btn)

    back_style = discord.ButtonStyle.danger if back_label == "Close Panel" else discord.ButtonStyle.secondary
    done_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "done", node.key),
    )
    done_btn.callback = on_cancel
    row.add_item(done_btn)

    if extra_buttons:
        for btn in extra_buttons:
            row.add_item(btn)

    builder.add_item(row)

    return builder.build()


def build_select_view(
    node: PanelNode,
    current_values: list,
    guild: discord.Guild,
    on_save: Callable[[discord.Interaction, list], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    on_clear: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    back_label: str = "Back",
    is_premium: bool = False,
    on_create: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    create_label: str = "Create",
) -> discord.ui.LayoutView:
    """Build a select view for a PanelNode with kind in (role_select, channel_select, option_select).

    The component auto-saves on change (no explicit Save button); Back navigates
    to the parent; Clear (if provided) removes all values. ``on_create`` (if
    provided) renders the inline create button (standard §11): every role/channel
    select editor lets the admin create the entity right where it is picked,
    instead of hunting for a separate create node.
    """
    builder = AdminLayoutBuilder()

    node_label = _effective_label(node, is_premium)
    builder.add_header(f"## {node_label}")

    # Read-only description block (#4d0eb3 accent)
    desc_text = node.description or f"Select values for **{node_label}**."
    builder.add_item(readonly_container(discord.ui.TextDisplay(desc_text)))

    # Current value display (editable block, no accent)
    if node.kind == "role_select":
        if current_values:
            mentions = [f"<@&{int(rid)}>" for rid in current_values]
            current_text = f"**Currently assigned:** {', '.join(mentions)}"
        else:
            current_text = "*No roles currently assigned.*"

    elif node.kind == "channel_select":
        is_category_only = (
            node.channel_types is not None
            and len(node.channel_types) == 1
            and node.channel_types[0] == discord.ChannelType.category
        )
        noun = "category" if is_category_only else "channel"
        if current_values:
            parts = []
            for _cid in current_values:
                ch = guild.get_channel(int(_cid))
                if ch is None:
                    parts.append(f"Unknown ({_cid})")
                elif is_category_only:
                    parts.append(ch.name)
                else:
                    parts.append(ch.mention)
            label = f"Current {noun}" if len(parts) == 1 else f"Current {noun}s"
            current_text = f"**{label}:** {', '.join(parts)}"
        else:
            current_text = f"*No {noun} currently set.*"

    elif node.kind == "option_select":
        if current_values:
            opt_label_map = {str(opt[0]): opt[1] for opt in (node.options or [])}
            names = [opt_label_map.get(str(v), str(v)) for v in current_values]
            current_text = f"**Currently selected:** {', '.join(names)}"
        else:
            current_text = "*Nothing currently selected.*"
    else:
        current_text = ""

    # Build the select component
    if node.kind == "role_select":
        component = discord.ui.RoleSelect(
            placeholder=f"Select roles for {node.label}...",
            custom_id=cid("editor", "select", node.key),
            min_values=node.min_values,
            max_values=node.max_values,
            default_values=[discord.Object(id=int(rid)) for rid in current_values],
        )

        async def _role_cb(interaction: discord.Interaction):
            role_ids = [int(rid) for rid in interaction.data.get("resolved", {}).get("roles", {}).keys()]
            await on_save(interaction, role_ids)

        component.callback = _role_cb

    elif node.kind == "channel_select":
        effective_max = node.max_values
        if is_premium and node.premium_max_values is not None:
            effective_max = node.premium_max_values
        select_kwargs = dict(
            placeholder=f"Select channel for {node.label}...",
            custom_id=cid("editor", "select", node.key),
            min_values=node.min_values,
            max_values=effective_max,
            default_values=[discord.Object(id=int(v)) for v in current_values],
        )
        if node.channel_types:
            select_kwargs["channel_types"] = node.channel_types
        component = discord.ui.ChannelSelect(**select_kwargs)

        async def _channel_cb(interaction: discord.Interaction):
            channel_ids = [int(cid) for cid in interaction.data.get("values", [])]
            await on_save(interaction, channel_ids)

        component.callback = _channel_cb

    elif node.kind == "option_select":
        current_strs = [str(v) for v in current_values]
        _prem = node.premium_values or set()
        option_objects = []
        for opt in (node.options or []):
            val, lbl = str(opt[0]), opt[1]
            desc = opt[2] if len(opt) > 2 else None
            if val in _prem and not is_premium:
                lbl = f"💎 {lbl}"
                desc = "Requires Premium subscription"
            option_objects.append(
                discord.SelectOption(
                    label=lbl,
                    value=val,
                    description=desc,
                    default=(val in current_strs),
                )
            )
        component = discord.ui.Select(
            placeholder="Select one or more options...",
            custom_id=cid("editor", "select", node.key),
            min_values=node.min_values,
            max_values=min(node.max_values, len(option_objects)) if option_objects else 1,
            options=option_objects,
        )

        async def _option_cb(interaction: discord.Interaction):
            await on_save(interaction, interaction.data["values"])

        component.callback = _option_cb

    else:
        return create_empty_layout(f"Unknown node kind: {node.kind!r}")

    # Wrap current-value text + active select in editable_container (no accent)
    select_row = discord.ui.ActionRow()
    select_row.add_item(component)
    builder.add_item(editable_container(
        discord.ui.TextDisplay(current_text or f"**Edit {node.label}:**"),
        select_row,
    ))

    # Back + optional Clear row
    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "back", node.key),
    )
    back_btn.callback = on_back
    btn_row = discord.ui.ActionRow()
    btn_row.add_item(back_btn)

    if on_clear is not None:
        clear_btn = discord.ui.Button(
            label="Clear",
            style=discord.ButtonStyle.danger,
            custom_id=cid("editor", "clear", node.key),
            disabled=(len(current_values) == 0),
        )
        clear_btn.callback = on_clear
        btn_row.add_item(clear_btn)

    if on_create is not None:
        create_btn = discord.ui.Button(
            label=create_label,
            style=discord.ButtonStyle.primary,
            custom_id=cid("editor", "create", node.key),
        )
        create_btn.callback = on_create
        btn_row.add_item(create_btn)

    builder.add_item(btn_row)

    return builder.build()


# -- Modal input support -------------------------------------------------------

class PanelInputModal(discord.ui.Modal):
    """Generic single-field modal used by build_modal_trigger_view.

    ``category_picker=True`` (channel-create flows) adds an optional
    parent-category select under the name field; the submit callback then
    receives ``(interaction, value, category_id | None)`` instead of
    ``(interaction, value)`` - ``None`` when the admin skipped the picker.
    ``category_default`` pre-selects a category (Try Again keeps the pick).
    """

    def __init__(
        self,
        *,
        title: str,
        label: str,
        placeholder: str,
        min_length: int,
        max_length: int,
        default: str,
        on_submit_callback: Callable[..., Awaitable[None]],
        paragraph: bool = False,
        required: bool = True,
        category_picker: bool = False,
        category_default: Optional[int] = None,
    ):
        super().__init__(title=title)
        self._callback = on_submit_callback
        self.category_select: Optional[discord.ui.ChannelSelect] = None
        self.value_input = discord.ui.TextInput(
            label=None if category_picker else label,
            placeholder=placeholder or None,
            required=required,
            style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
            min_length=min_length,
            max_length=max_length,
            default=default or None,
        )
        if not category_picker:
            self.add_item(self.value_input)
        else:
            # With the picker, every field rides in a Label component -
            # Discord's modal layout does not mix bare text inputs with Labels.
            self.add_item(discord.ui.Label(text=label, component=self.value_input))
            self.category_select = discord.ui.ChannelSelect(
                channel_types=[discord.ChannelType.category],
                placeholder="No category",
                required=False,
                min_values=0,
                max_values=1,
                default_values=(
                    [discord.Object(id=category_default, type=discord.abc.GuildChannel)]
                    if category_default else []
                ),
            )
            self.add_item(discord.ui.Label(
                text="Category",
                description="Optional - pick where the channel goes, or leave empty.",
                component=self.category_select,
            ))

    async def on_submit(self, interaction: discord.Interaction):
        value = self.value_input.value.strip()
        if self.category_select is None:
            await self._callback(interaction, value)
            return
        picked = self.category_select.values
        await self._callback(interaction, value, picked[0].id if picked else None)


def build_modal_trigger_view(
    node: PanelNode,
    current_values: list,
    guild: discord.Guild,
    on_save: Callable[[discord.Interaction, discord.Interaction, str], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    on_clear: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    back_label: str = "Back",
    attempted: Optional[str] = None,
    is_premium: bool = False,
) -> discord.ui.LayoutView:
    """Build a trigger view for a PanelNode with kind="modal_input".

    Shows the current value and a button that opens a modal for editing.
    on_save receives (button_interaction, modal_interaction, raw_value).

    When `attempted` is supplied (after a validation failure), the modal opens
    pre-filled with that value instead of the current one so the user can
    correct their input without retyping.
    """
    builder = AdminLayoutBuilder()

    node_label = _effective_label(node, is_premium)
    builder.add_header(f"## {node_label}")

    desc_text = node.description or f"Set a value for **{node_label}**."
    builder.add_item(readonly_container(discord.ui.TextDisplay(desc_text)))

    current_text = (
        f"**Current value:** {current_values[0]}" if current_values
        else "*Not currently set.*"
    )

    set_btn = discord.ui.Button(
        label=f"Set {node.label}",
        style=discord.ButtonStyle.primary,
        custom_id=cid("editor", "set", node.key),
    )

    async def set_btn_callback(bi: discord.Interaction):
        async def _on_submit(mi: discord.Interaction, raw: str):
            await on_save(bi, mi, raw)

        if attempted is not None:
            modal_default = attempted
        elif current_values:
            modal_default = current_values[0]
        else:
            modal_default = ""
        modal = PanelInputModal(
            title=node.modal_title or f"Set {node.label}",
            label=node.modal_label or "Value",
            placeholder=node.modal_placeholder or "",
            min_length=node.modal_min_length,
            max_length=node.modal_max_length,
            default=modal_default,
            on_submit_callback=_on_submit,
            paragraph=node.modal_paragraph,
            required=node.modal_required,
        )
        await bi.response.send_modal(modal)

    set_btn.callback = set_btn_callback

    set_row = discord.ui.ActionRow()
    set_row.add_item(set_btn)
    if on_clear is not None:
        clear_btn = discord.ui.Button(
            label="Clear",
            style=discord.ButtonStyle.danger,
            custom_id=cid("editor", "clear", node.key),
            disabled=(len(current_values) == 0),
        )
        clear_btn.callback = on_clear
        set_row.add_item(clear_btn)

    builder.add_item(editable_container(
        discord.ui.TextDisplay(current_text),
        set_row,
    ))

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "back", node.key),
    )
    back_btn.callback = on_back
    back_row = discord.ui.ActionRow()
    back_row.add_item(back_btn)
    builder.add_item(back_row)

    return builder.build()


# -- Dual-field modal input support --------------------------------------------

class _PanelDualInputModal(discord.ui.Modal):
    """Two-field modal used by build_dual_modal_trigger_view."""

    def __init__(
        self,
        *,
        title: str,
        label: str,
        placeholder: str,
        min_length: int,
        max_length: int,
        default: str,
        label_2: str,
        placeholder_2: str,
        min_length_2: int,
        max_length_2: int,
        default_2: str,
        on_submit_callback: Callable[[discord.Interaction, str, str], Awaitable[None]],
    ):
        super().__init__(title=title)
        self._callback = on_submit_callback
        self.value_input = discord.ui.TextInput(
            label=label,
            placeholder=placeholder or None,
            required=True,
            style=discord.TextStyle.short,
            min_length=min_length,
            max_length=max_length,
            default=default or None,
        )
        self.value_input_2 = discord.ui.TextInput(
            label=label_2,
            placeholder=placeholder_2 or None,
            required=False,
            style=discord.TextStyle.paragraph,
            min_length=min_length_2,
            max_length=max_length_2,
            default=default_2 or None,
        )
        self.add_item(self.value_input)
        self.add_item(self.value_input_2)

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(
            interaction,
            self.value_input.value.strip(),
            self.value_input_2.value.strip(),
        )


# Summary strings that mean "this setting has no value yet".
_UNSET_SUMMARIES = ("Not configured", "Not set", "Not assigned", "Empty")


def _counts_toward_progress(node: PanelNode) -> bool:
    """True when a node is a setting an admin can give a value to.

    Read-only screens and one-shot commands (kind="action" - View Status,
    Export, Reset, Purge) have no stored value, so they can never read as
    configured and must not inflate the category badge.

    A node can override the kind-based inference with ``counts_as_setting``. That
    exists because ``kind="action"`` covers two unrelated things: stateless one-shots
    (correctly excluded) and bespoke settings editors that own real stored config
    (which must be counted, or a category built entirely from them shows no badge at
    all while its settings are plainly configurable).
    """
    if node.counts_as_setting is not None:
        return node.counts_as_setting
    if node.kind == "action":
        return False
    if node.kind == "menu":
        # A toggle-only menu is a real on/off setting. A menu with children is
        # a container - its children are counted individually. A menu with
        # neither is a label-only stub.
        return bool(node.toggle_get) and not node.children
    return True


def _compact_category_summary(
    cat_node: PanelNode,
    cat_summaries: dict[str, str | dict[str, str]],
) -> str:
    """Build a one-line compact summary for a category.

    Counts only configurable settings - see ``_counts_toward_progress``.
    Returns "" when the category holds no settable items at all, so the caller
    can render the label on its own instead of a meaningless "0 of 0".
    A childless top-level node summarizes itself under the "__self__" sentinel
    (see AdminCog._gather_deep_summaries) - render that verbatim.
    """
    self_summary = cat_summaries.get("__self__")
    if isinstance(self_summary, str) and self_summary:
        return self_summary

    configured = 0
    total = 0
    for child_key, child_node in cat_node.children.items():
        val = cat_summaries.get(child_key)
        if isinstance(val, dict):
            for sub_key, sub_val in val.items():
                sub_node = child_node.children.get(sub_key)
                if sub_node is None or not _counts_toward_progress(sub_node):
                    continue
                total += 1
                if sub_val not in _UNSET_SUMMARIES:
                    configured += 1
        else:
            if not _counts_toward_progress(child_node):
                continue
            total += 1
            if (val or "Not configured") not in _UNSET_SUMMARIES:
                configured += 1

    if total == 0:
        return ""
    if configured == 0:
        return "Not configured"
    return f"{configured} of {total} configured"


def build_overview_view(
    root_node: PanelNode,
    deep_summary: dict[str, dict[str, str | dict[str, str]]],
    toggle_states: dict[str, bool | None],
    locked_keys: set[str],
    on_category_select: Callable[[discord.Interaction, str], Awaitable[None]],
    preamble_items: list[discord.ui.Item] | None = None,
    extra_buttons: list[discord.ui.Button] | None = None,
    compact: bool = True,
    title_override: str | None = None,
    footer_text: str | None = None,
    is_premium: bool = False,
) -> discord.ui.LayoutView:
    """Build the persistent overview view (Message 1) showing all settings.

    Args:
        root_node:          The MAIN_PANEL PanelNode.
        deep_summary:       {cat_key: {child_key: summary_str | {sub_key: str}}}
        toggle_states:      {cat_key: bool | None}
        locked_keys:        Set of category keys that are locked.
        on_category_select: Async callback (interaction, cat_key).
        preamble_items:     Optional items inserted after header (e.g. setup guide).
        extra_buttons:      Optional buttons appended to the action row.
        compact:            If True, show one-line summaries per category (default).
        title_override:     If set, replaces root_node.label as the header text.
        footer_text:        If non-empty, rendered at the bottom of the view.
    """
    builder = AdminLayoutBuilder()
    _locked = locked_keys or set()

    header_text = title_override if title_override is not None else root_node.label
    builder.add_header(f"## {header_text}")

    # Read-only setup guide (preamble_items) \u2014 only shown when toggled on
    if preamble_items:
        builder.add_item(readonly_container(*preamble_items))

    # Read-only config details \u2014 current state summary
    detail_items: list[discord.ui.Item] = []
    if compact:
        lines = []
        for cat_key, cat_node in root_node.children.items():
            cat_summaries = deep_summary.get(cat_key, {})
            lock_prefix = "\U0001f512 " if cat_key in _locked else ""
            toggle = toggle_states.get(cat_key)

            summary = _compact_category_summary(cat_node, cat_summaries)
            cat_label = _effective_label(cat_node, is_premium)
            if toggle is not None:
                status = "Enabled" if toggle else "Disabled"
                suffix = f" ({summary})" if summary else ""
                lines.append(f"**{lock_prefix}{cat_label}** - {status}{suffix}")
            elif summary:
                lines.append(f"**{lock_prefix}{cat_label}** - {summary}")
            else:
                lines.append(f"**{lock_prefix}{cat_label}**")

        detail_items.append(discord.ui.TextDisplay("\n".join(lines)))
    else:
        for cat_key, cat_node in root_node.children.items():
            cat_summaries = deep_summary.get(cat_key, {})
            lock_prefix = "\U0001f512 " if cat_key in _locked else ""

            toggle = toggle_states.get(cat_key)
            cat_label = _effective_label(cat_node, is_premium)
            if toggle is not None:
                status = "Enabled" if toggle else "Disabled"
                header = f"**{lock_prefix}{cat_label}** - {status}"
            else:
                header = f"**{lock_prefix}{cat_label}**"

            lines = [header]
            for child_key, child_node in cat_node.children.items():
                val = cat_summaries.get(child_key, "Not configured")
                child_label_2 = _effective_label(child_node, is_premium)
                if isinstance(val, dict):
                    lines.append(f"  {child_label_2}:")
                    for sub_key, sub_node in child_node.children.items():
                        sub_label = _effective_label(sub_node, is_premium)
                        # Read-only screens and one-shot commands hold no value.
                        if sub_node.kind == "action":
                            lines.append(f"    \u2022 {sub_label}")
                            continue
                        sub_val = val.get(sub_key, "Not configured")
                        lines.append(f"    \u2022 {sub_label}: {sub_val}")
                elif child_node.kind == "action":
                    lines.append(f"  \u2022 {child_label_2}")
                else:
                    lines.append(f"  \u2022 {child_label_2}: {val}")

            detail_items.append(discord.ui.TextDisplay("\n".join(lines)))

    if detail_items:
        builder.add_item(readonly_container(*detail_items))

    builder.add_text("Select a category below to configure it.")

    # Category select dropdown - inject a disabled-style "── Feature
    # Configurations ──" divider between main and feature groups per
    # ADMIN_PANEL_STANDARD.md §1 / §7.
    options: list[discord.SelectOption] = []
    prev_group: str | None = None
    for key, child in root_node.children.items():
        group = getattr(child, "category_group", "main")
        if group == "feature" and prev_group == "main":
            options.append(discord.SelectOption(
                label="── Feature Configurations ──",
                value=DASHBOARD_FEATURE_SEPARATOR_VALUE,
                description="(divider - not selectable)",
            ))
        child_label = _effective_label(child, is_premium)
        # Rendered verbatim: validate_panel guarantees at startup that the
        # blurb (or, absent one, the description) fits Discord's option cap.
        desc = child.blurb or child.description or None
        options.append(discord.SelectOption(
            label=f"\U0001f512 {child_label}" if key in _locked else child_label,
            value=key,
            description=desc,
        ))
        prev_group = group
    select = discord.ui.Select(
        placeholder="Select a category...",
        custom_id=cid("dash", "select"),
        options=options,
    )

    async def _select_cb(interaction: discord.Interaction):
        from .base import build_notice_layout
        chosen = interaction.data["values"][0]
        if chosen == DASHBOARD_FEATURE_SEPARATOR_VALUE:
            await interaction.response.send_message(
                view=build_notice_layout(
                    "Pick a category",
                    "That line is a divider - choose an actual category.",
                ),
                ephemeral=True,
            )
            return
        await on_category_select(interaction, chosen)

    select.callback = _select_cb
    builder.add_select(select)

    # Action row for extra buttons (e.g. setup guide toggle)
    if extra_buttons:
        row = discord.ui.ActionRow()
        for btn in extra_buttons:
            row.add_item(btn)
        builder.add_item(row)

    if footer_text:
        builder.add_separator()
        builder.add_text(footer_text)

    return builder.build()


def build_dual_modal_trigger_view(
    node: PanelNode,
    current_values: list,
    guild: discord.Guild,
    on_save: Callable[[discord.Interaction, discord.Interaction, str, str], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    back_label: str = "Back",
    is_premium: bool = False,
) -> discord.ui.LayoutView:
    """Build a trigger view for a PanelNode with kind="dual_modal_input".

    Shows both current values and a button that opens a two-field modal.
    on_save receives (button_interaction, modal_interaction, val1, val2).
    current_values is expected to be a 2-element list [field_1, field_2].
    """
    builder = AdminLayoutBuilder()

    builder.add_header(f"## {_effective_label(node, is_premium)}")

    val1 = current_values[0] if len(current_values) > 0 else ""
    val2 = current_values[1] if len(current_values) > 1 else ""

    desc_text = node.description or f"Set values for **{node.label}**."
    builder.add_item(readonly_container(discord.ui.TextDisplay(desc_text)))

    if val1 or val2:
        lines = []
        if val1:
            lines.append(f"**{node.modal_label or 'Field 1'}:** {val1}")
        if val2:
            lines.append(f"**{node.modal_label_2 or 'Field 2'}:** {val2}")
        current_text = "\n".join(lines)
    else:
        current_text = "*Not currently set.*"

    edit_btn = discord.ui.Button(
        label="Edit",
        style=discord.ButtonStyle.primary,
        custom_id=cid("editor", "edit", node.key),
    )

    async def edit_btn_callback(bi: discord.Interaction):
        async def _on_submit(mi: discord.Interaction, raw1: str, raw2: str):
            await on_save(bi, mi, raw1, raw2)

        modal = _PanelDualInputModal(
            title=node.modal_title or f"Set {node.label}",
            label=node.modal_label or "Field 1",
            placeholder=node.modal_placeholder or "",
            min_length=node.modal_min_length,
            max_length=node.modal_max_length,
            default=val1,
            label_2=node.modal_label_2 or "Field 2",
            placeholder_2=node.modal_placeholder_2 or "",
            min_length_2=node.modal_min_length_2,
            max_length_2=node.modal_max_length_2,
            default_2=val2,
            on_submit_callback=_on_submit,
        )
        await bi.response.send_modal(modal)

    edit_btn.callback = edit_btn_callback

    edit_row = discord.ui.ActionRow()
    edit_row.add_item(edit_btn)
    builder.add_item(editable_container(
        discord.ui.TextDisplay(current_text),
        edit_row,
    ))

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "back", node.key),
    )
    back_btn.callback = on_back
    back_row = discord.ui.ActionRow()
    back_row.add_item(back_btn)
    builder.add_item(back_row)

    return builder.build()


# -- Dict Editor --------------------------------------------------------------

def _dict_channel_name(guild: discord.Guild | None, key) -> str:
    """Resolve a channel key to ``#name``.

    Falls back to the raw id marked ``(deleted)`` when the channel is gone, and to
    the bare id when no guild was supplied (nothing can be resolved).
    """
    if guild is None:
        return str(key)
    try:
        channel = guild.get_channel(int(key))
    except (TypeError, ValueError):
        channel = None
    if channel is not None:
        return f"#{channel.name}"
    return f"{key} (deleted)"


def _dict_role_name(guild: discord.Guild | None, value) -> str:
    """Resolve a role value to ``@name``.

    Falls back to the raw id marked ``(deleted)`` when the role is gone, and to the
    bare id when no guild was supplied.
    """
    if guild is None:
        return str(value)
    try:
        role = guild.get_role(int(value))
    except (TypeError, ValueError):
        role = None
    if role is not None:
        return f"@{role.name}"
    return f"{value} (deleted)"


def _dict_key_display(node: PanelNode, key):
    """Key as it appears in the entries listing (channel keys render as mentions)."""
    if node.dict_key_kind == "channel":
        return f"<#{key}>"
    return key


def _dict_value_display(node: PanelNode, value):
    """Value as it appears in the entries listing (role values render as mentions)."""
    if node.dict_value_kind == "role":
        return f"<@&{value}>"
    return value


def _dict_entry_option_label(
    node: PanelNode, key, value, guild: discord.Guild | None = None,
) -> str:
    """<=100-char option label for the Edit / Remove selects.

    Channel keys and role values are resolved to readable names so an admin never
    has to recognise a snowflake. Default text/text nodes get ``str(key)[:100]``,
    unchanged.
    """
    if node.dict_key_kind == "channel":
        label = _dict_channel_name(guild, key)
    else:
        label = str(key)
    if node.dict_value_kind == "role":
        label = f"{label} - {_dict_role_name(guild, value)}"
    return label[:100]


def build_dict_editor_view(
    node: PanelNode,
    current_values: dict,
    *,
    on_add: Callable[[discord.Interaction], Awaitable[None]],
    on_edit: Callable[[discord.Interaction, str], Awaitable[None]],
    on_remove: Callable[[discord.Interaction, str], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    back_label: str = "Back",
    is_premium: bool = False,
    guild: discord.Guild | None = None,
) -> discord.ui.LayoutView:
    """Build a view for a PanelNode with kind="dict_editor".

    Renders the current key->value map as bullet lines and exposes Add /
    Edit / Remove / Back controls. Edit and Remove use a select dropdown of
    existing keys; the orchestrator opens a dual-modal for Add/Edit submission.

    Args:
        node:           The dict_editor PanelNode.
        current_values: Current {key: value} mapping persisted in storage.
        on_add:         Async (interaction) - open add modal.
        on_edit:        Async (interaction, target_key) - open edit modal pre-filled.
        on_remove:      Async (interaction, target_key) - delete entry.
        on_back:        Async (interaction) - leave editor.
        back_label:     "Back" or "Close" depending on parent context.
        guild:          Guild used to resolve channel keys / role values to names.
                        Optional: without it ids render raw (default text/text
                        editors never need it).
    """
    builder = AdminLayoutBuilder()

    builder.add_header(f"## {_effective_label(node, is_premium)}")

    if node.description:
        builder.add_item(readonly_container(discord.ui.TextDisplay(node.description)))

    if current_values:
        lines = [
            f"• **{_dict_key_display(node, k)}**: {_dict_value_display(node, v)}"
            for k, v in current_values.items()
        ]
        if node.dict_max_entries is not None:
            lines.append(f"\n*{len(current_values)} of {node.dict_max_entries} entries*")
        # The edit/remove selects below are capped at Discord's 25-option limit. Surface
        # that so entries past 25 aren't a silent trap (proper fix: paginate the selects).
        if len(current_values) > 25:
            lines.append(
                "\n*Only the first 25 entries can be edited or removed here (Discord limit); "
                "remove an earlier entry to reach the rest.*"
            )
        current_text = "\n".join(lines)
    else:
        current_text = "*No entries configured.*"

    # Add button
    add_disabled = (
        node.dict_max_entries is not None
        and len(current_values) >= node.dict_max_entries
    )
    add_btn = discord.ui.Button(
        label="Add Entry",
        style=discord.ButtonStyle.success,
        custom_id=cid("editor", "dict_add", node.key),
        disabled=add_disabled,
    )
    add_btn.callback = on_add

    editor_items: list[discord.ui.Item] = [discord.ui.TextDisplay(current_text)]

    add_row = discord.ui.ActionRow()
    add_row.add_item(add_btn)
    editor_items.append(add_row)

    if current_values:
        visible_entries = list(current_values.items())[:25]
        edit_options = [
            discord.SelectOption(
                label=_dict_entry_option_label(node, k, v, guild), value=str(k),
            )
            for k, v in visible_entries
        ]
        edit_select = discord.ui.Select(
            placeholder="Edit entry...",
            custom_id=cid("editor", "dict_edit", node.key),
            options=edit_options,
            min_values=1,
            max_values=1,
        )

        async def _edit_cb(interaction: discord.Interaction):
            await on_edit(interaction, interaction.data["values"][0])

        edit_select.callback = _edit_cb

        remove_options = [
            discord.SelectOption(
                label=_dict_entry_option_label(node, k, v, guild), value=str(k),
            )
            for k, v in visible_entries
        ]
        remove_select = discord.ui.Select(
            placeholder="Remove entry...",
            custom_id=cid("editor", "dict_remove", node.key),
            options=remove_options,
            min_values=1,
            max_values=1,
        )

        async def _remove_cb(interaction: discord.Interaction):
            await on_remove(interaction, interaction.data["values"][0])

        remove_select.callback = _remove_cb

        edit_row = discord.ui.ActionRow()
        edit_row.add_item(edit_select)
        editor_items.append(edit_row)

        remove_row = discord.ui.ActionRow()
        remove_row.add_item(remove_select)
        editor_items.append(remove_row)

    builder.add_item(editable_container(*editor_items))

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "dict_back", node.key),
    )
    back_btn.callback = on_back
    builder.add_action_row(back_btn)

    return builder.build()


def build_dict_key_channel_view(
    node: PanelNode,
    *,
    on_pick: Callable[[discord.Interaction, int], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    back_label: str = "Back",
    is_premium: bool = False,
) -> discord.ui.LayoutView:
    """Channel-key step of a ``dict_key_kind == "channel"`` dict_editor.

    Step 1 of Add: a native ChannelSelect (filtered by
    ``node.dict_key_channel_types``) whose pick is handed to ``on_pick`` as an int
    channel id; the orchestrator then runs the value step. Back returns to the
    entries list without changing anything.
    """
    builder = AdminLayoutBuilder()

    builder.add_header(f"## {_effective_label(node, is_premium)}")

    if node.dict_value_kind == "role":
        next_step = "You will pick the role for it next."
    else:
        next_step = (
            f"You will be asked for the **{node.dict_value_label or 'Value'}** next."
        )
    builder.add_item(readonly_container(discord.ui.TextDisplay(
        f"Pick the channel this entry applies to. {next_step}\n"
        "Picking a channel that already has an entry updates that entry."
    )))

    select_kwargs = dict(
        placeholder="Select a channel...",
        custom_id=cid("editor", "dict_key_channel", node.key),
        min_values=1,
        max_values=1,
    )
    if node.dict_key_channel_types:
        select_kwargs["channel_types"] = node.dict_key_channel_types
    component = discord.ui.ChannelSelect(**select_kwargs)

    async def _channel_cb(interaction: discord.Interaction):
        await on_pick(interaction, int(interaction.data["values"][0]))

    component.callback = _channel_cb

    select_row = discord.ui.ActionRow()
    select_row.add_item(component)
    builder.add_item(editable_container(
        discord.ui.TextDisplay(f"**{node.dict_key_label or 'Key'}:**"),
        select_row,
    ))

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "dict_key_back", node.key),
    )
    back_btn.callback = on_back
    builder.add_action_row(back_btn)

    return builder.build()


def build_dict_value_role_view(
    node: PanelNode,
    entry_key,
    *,
    current_role_id=None,
    on_pick: Callable[[discord.Interaction, int], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    back_label: str = "Back",
    is_premium: bool = False,
    guild: discord.Guild | None = None,
) -> discord.ui.LayoutView:
    """Role-value step of a ``dict_value_kind == "role"`` dict_editor.

    Shows which entry is being edited and a native RoleSelect (pre-filled with the
    entry's current role when it has one). The pick is handed to ``on_pick`` as an
    int role id; the orchestrator permission-checks it before persisting. Back
    returns to the entries list without changing anything.
    """
    builder = AdminLayoutBuilder()

    builder.add_header(f"## {_effective_label(node, is_premium)}")

    key_text = _dict_key_display(node, entry_key)
    builder.add_item(readonly_container(discord.ui.TextDisplay(
        f"Pick the role for **{node.dict_key_label or 'Key'}: {key_text}**.\n"
        "The bot has to be able to assign it, so it cannot be @everyone or a role "
        "managed by an integration, and it must sit below the bot's highest role."
    )))

    default_values = []
    if current_role_id:
        try:
            default_values = [discord.Object(id=int(current_role_id))]
        except (TypeError, ValueError):
            default_values = []

    current_text = (
        f"**Current role:** {_dict_role_name(guild, current_role_id)}"
        if current_role_id
        else "*No role set for this entry yet.*"
    )

    component = discord.ui.RoleSelect(
        placeholder="Select a role...",
        custom_id=cid("editor", "dict_value_role", node.key),
        min_values=1,
        max_values=1,
        default_values=default_values,
    )

    async def _role_cb(interaction: discord.Interaction):
        await on_pick(interaction, int(interaction.data["values"][0]))

    component.callback = _role_cb

    select_row = discord.ui.ActionRow()
    select_row.add_item(component)
    builder.add_item(editable_container(
        discord.ui.TextDisplay(current_text),
        select_row,
    ))

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "dict_value_back", node.key),
    )
    back_btn.callback = on_back
    builder.add_action_row(back_btn)

    return builder.build()


# -- File Upload --------------------------------------------------------------

class PanelFileUploadModal(discord.ui.Modal):
    """Modal with a single file upload field for panel file_upload nodes."""

    upload_label = discord.ui.Label(
        text="File",
        component=discord.ui.FileUpload(
            custom_id=cid("modal", "upload"),
            min_values=1,
            max_values=1,
        ),
    )

    def __init__(self, *, title: str, on_submit_callback: Callable):
        super().__init__(title=title)
        self._callback = on_submit_callback

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, self.upload_label.component.values[0])


def build_file_upload_view(
    node: PanelNode,
    current_values: list,
    guild: discord.Guild,
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    on_clear: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    back_label: str = "Back",
    on_upload: Optional[Callable] = None,
    is_premium: bool = False,
) -> discord.ui.LayoutView:
    """Build a status view for a PanelNode with kind="file_upload".

    Shows whether a custom payload is active and provides Upload / Download
    Template (if `node.template_data`) / Clear / Back buttons.

    Args:
        node:           The file_upload PanelNode.
        current_values: List with one element (raw payload) if active, else empty.
        guild:          The Discord guild.
        on_back:        Async callback (interaction) to navigate back.
        on_clear:       Optional async callback to clear stored payload.
        back_label:     Label for the back button ("Back" or "Close").
        on_upload:      Optional async (button_interaction, modal_interaction, attachment).
    """
    builder = AdminLayoutBuilder()

    builder.add_header(f"## {_effective_label(node, is_premium)}")

    if node.description:
        builder.add_item(readonly_container(discord.ui.TextDisplay(node.description)))

    if current_values:
        current_text = "**Custom payload:** Active"
    else:
        current_text = "**Custom payload:** Not set - using default"

    btn_row = discord.ui.ActionRow()

    if on_upload is not None:
        upload_btn = discord.ui.Button(
            label=f"Upload {node.label}",
            style=discord.ButtonStyle.primary,
            custom_id=cid("editor", "upload", node.key),
        )

        async def upload_btn_cb(bi: discord.Interaction):
            async def _on_submit(mi, attachment):
                await on_upload(bi, mi, attachment)

            modal = PanelFileUploadModal(
                title=f"Upload {node.label}"[:45],
                on_submit_callback=_on_submit,
            )
            await bi.response.send_modal(modal)

        upload_btn.callback = upload_btn_cb
        btn_row.add_item(upload_btn)

    if node.template_data is not None:
        import io

        template_btn = discord.ui.Button(
            label="Download Template",
            style=discord.ButtonStyle.secondary,
            custom_id=cid("editor", "template", node.key),
        )

        async def template_btn_cb(ti: discord.Interaction):
            template_bytes, filename = node.template_data()
            await ti.response.send_message(
                file=discord.File(io.BytesIO(template_bytes), filename=filename),
                ephemeral=True,
            )

        template_btn.callback = template_btn_cb
        btn_row.add_item(template_btn)

    if on_clear is not None:
        clear_btn = discord.ui.Button(
            label="Clear",
            style=discord.ButtonStyle.danger,
            custom_id=cid("editor", "clear", node.key),
            disabled=(len(current_values) == 0),
        )
        clear_btn.callback = on_clear
        btn_row.add_item(clear_btn)

    # Editable block: current payload status + upload/template/clear buttons
    builder.add_item(editable_container(
        discord.ui.TextDisplay(current_text),
        btn_row,
    ))

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "back", node.key),
    )
    back_btn.callback = on_back
    back_row = discord.ui.ActionRow()
    back_row.add_item(back_btn)
    builder.add_item(back_row)

    return builder.build()


# -- Paginated list -----------------------------------------------------------

def build_paginated_list_view(
    node: PanelNode,
    page_items: list,
    page: int,
    total: int,
    guild: discord.Guild,
    on_prev: Callable[[discord.Interaction], Awaitable[None]],
    on_next: Callable[[discord.Interaction], Awaitable[None]],
    on_pick: Callable[[discord.Interaction, str], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    back_label: str = "Back",
    is_premium: bool = False,
) -> discord.ui.LayoutView:
    """Build a paginated list view for a PanelNode with kind="paginated_list".

    ``page_items`` is the already-sliced window for the current ``page`` (0-based);
    ``total`` is the full item count. When ``node.list_action_label`` is set and the
    page is non-empty, a per-item Select (bounded to the page, so never > 25 options)
    dispatches the chosen item's value to ``on_pick``.
    """
    builder = AdminLayoutBuilder()

    node_label = _effective_label(node, is_premium)
    builder.add_header(f"## {node_label}")

    if node.description:
        builder.add_item(readonly_container(discord.ui.TextDisplay(node.description)))

    page_size = max(1, node.list_page_size)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = page * page_size

    if total == 0:
        body_text = "*The list is empty.*"
    else:
        lines = [
            node.list_format_line(item, start + offset)
            for offset, item in enumerate(page_items)
        ]
        end = start + len(page_items)
        lines.append(f"\n*Showing {start + 1}-{end} of {total}* (page {page + 1}/{total_pages})")
        body_text = "\n".join(lines)

    editable_items: list[discord.ui.Item] = [discord.ui.TextDisplay(body_text)]

    # Per-item action select (bounded to the current page -> never exceeds 25).
    if node.list_action_label and page_items:
        options = [
            discord.SelectOption(
                label=node.list_item_option_label(item, start + offset)[:100],
                value=str(node.list_item_value(item)),
            )
            for offset, item in enumerate(page_items)
        ]
        action_select = discord.ui.Select(
            placeholder=f"{node.list_action_label}…",
            custom_id=cid("editor", "list_action", node.key),
            options=options,
            min_values=1,
            max_values=1,
        )

        async def _action_cb(interaction: discord.Interaction):
            await on_pick(interaction, interaction.data["values"][0])

        action_select.callback = _action_cb
        action_row = discord.ui.ActionRow()
        action_row.add_item(action_select)
        editable_items.append(action_row)

    builder.add_item(editable_container(*editable_items))

    # Navigation + back row.
    nav_row = discord.ui.ActionRow()

    prev_btn = discord.ui.Button(
        label="◀ Prev",
        style=discord.ButtonStyle.secondary,
        custom_id=cid("editor", "list_prev", node.key),
        disabled=(page <= 0),
    )
    prev_btn.callback = on_prev
    nav_row.add_item(prev_btn)

    next_btn = discord.ui.Button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id=cid("editor", "list_next", node.key),
        disabled=(page >= total_pages - 1),
    )
    next_btn.callback = on_next
    nav_row.add_item(next_btn)

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "back", node.key),
    )
    back_btn.callback = on_back
    nav_row.add_item(back_btn)

    builder.add_item(nav_row)

    return builder.build()


def build_confirm_view(
    title: str,
    body: str,
    on_confirm: Callable[[discord.Interaction], Awaitable[None]],
    on_cancel: Callable[[discord.Interaction], Awaitable[None]],
    *,
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    confirm_style: discord.ButtonStyle = discord.ButtonStyle.danger,
    key: str = "confirm",
) -> discord.ui.LayoutView:
    """Build a generic Confirm/Cancel prompt (orange notice accent).

    Used by destructive panel flows (e.g. paginated_list item actions) to require
    an explicit confirmation before acting.
    """
    builder = AdminLayoutBuilder()
    builder.add_header(f"## {title}")
    builder.add_item(notice_container(discord.ui.TextDisplay(body)))

    confirm_btn = discord.ui.Button(
        label=confirm_label,
        style=confirm_style,
        custom_id=cid("confirm", "save", key),
    )
    confirm_btn.callback = on_confirm
    cancel_btn = discord.ui.Button(
        label=cancel_label,
        style=discord.ButtonStyle.secondary,
        custom_id=cid("confirm", "cancel", key),
    )
    cancel_btn.callback = on_cancel
    row = discord.ui.ActionRow()
    row.add_item(confirm_btn)
    row.add_item(cancel_btn)
    builder.add_item(row)

    return builder.build()


# -- Grouped paginated select -------------------------------------------------

def build_grouped_region_view(
    node: PanelNode,
    regions: list[tuple[str, str]],
    current_label: str,
    on_pick_region: Callable[[discord.Interaction, str], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    back_label: str = "Back",
    is_premium: bool = False,
) -> discord.ui.LayoutView:
    """Build the group-picker step for a PanelNode with kind="grouped_paginated_select".

    ``regions`` is a list of ``(value, label)``; picking one dispatches the value
    to ``on_pick_region`` (which then renders the paginated item step via
    ``build_paginated_list_view``). ``current_label`` is a human string for the
    currently-saved value (shown for context), or "" when nothing is set.
    """
    builder = AdminLayoutBuilder()

    node_label = _effective_label(node, is_premium)
    builder.add_header(f"## {node_label}")

    desc_text = node.description or f"Select a value for **{node_label}**."
    builder.add_item(readonly_container(discord.ui.TextDisplay(desc_text)))

    current_text = (
        f"**Current:** {current_label}" if current_label
        else "*Nothing currently set.*"
    )

    options = [
        discord.SelectOption(label=label[:100], value=value)
        for value, label in regions[:25]
    ]
    component = discord.ui.Select(
        placeholder="Select a region...",
        custom_id=cid("editor", "group_select", node.key),
        min_values=1,
        max_values=1,
        options=options,
    )

    async def _region_cb(interaction: discord.Interaction):
        await on_pick_region(interaction, interaction.data["values"][0])

    component.callback = _region_cb
    select_row = discord.ui.ActionRow()
    select_row.add_item(component)
    builder.add_item(editable_container(
        discord.ui.TextDisplay(current_text),
        select_row,
    ))

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=cid("editor", "back", node.key),
    )
    back_btn.callback = on_back
    back_row = discord.ui.ActionRow()
    back_row.add_item(back_btn)
    builder.add_item(back_row)

    return builder.build()
