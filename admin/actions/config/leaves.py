# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Config-bound leaf factories - create PanelNode leaves wired to a config path.

A bot calls these with a dotted config ``path`` (and a label) and gets a ready
PanelNode whose get/set/clear route through the config doers. Covers the bulk of
every bot's admin actions (channels, roles, options, text, ints, dict maps,
grouped pickers).
"""

from __future__ import annotations

from typing import Optional

from ...views.panel_engine import PanelNode
from .fields import (
    get_config_field, set_config_field, clear_config_field,
    get_config_list, set_config_list,
)
from ..data.colors import hex_validator, to_hex


def _id_accessors(path: str, *, multi: bool, as_str: bool = False):
    """(get, set, clear) for an id list/scalar at ``path`` (roles/channels).

    ``as_str=True`` stores/returns ids as strings (for bots that key state by string
    id, e.g. EcomRebuild) instead of ints. Discord's role/channel selects render the
    current selection from either form."""
    cast = str if as_str else int

    async def _get(guild_id):
        if multi:
            return [cast(x) for x in await get_config_list(guild_id, path)]
        v = await get_config_field(guild_id, path)
        return [cast(v)] if v else []

    async def _set(guild_id, values):
        if multi:
            return await set_config_list(guild_id, path, [cast(v) for v in values])
        if values:
            return await set_config_field(guild_id, path, cast(values[0]))
        return await clear_config_field(guild_id, path)

    async def _clear(guild_id):
        return await clear_config_field(guild_id, path)

    return _get, _set, _clear


def role_leaf(key, path, *, label, description="", multi=False, max_values=10,
              requires_role_manage=False, premium_label=None,
              pre_check=None, str_ids=False, value_validator=None) -> PanelNode:
    """role_select leaf storing a single role id (``multi=False``) or a list.

    ``pre_check`` is an optional ``async (interaction, guild_id) -> LayoutView | None`` gate
    (e.g. ``auth.manage_guild_pre_check`` for admin/mod role-access nodes).
    ``str_ids=True`` stores ids as strings (see ``_id_accessors``).
    ``value_validator`` is an optional ``async (guild, values) -> error_str | None`` run
    before saving (e.g. the delegation-role check for access lists)."""
    g, s, c = _id_accessors(path, multi=multi, as_str=str_ids)
    return PanelNode(
        key=key, label=label, kind="role_select", description=description,
        get_values=g, set_values=s, clear_values=c,
        min_values=0, max_values=(max_values if multi else 1),
        requires_role_manage=requires_role_manage,
        premium_label=premium_label, pre_check=pre_check,
        value_validator=value_validator,
    )


def channel_leaf(key, path, *, label, description="", channel_types=None, multi=False,
                 max_values=10, required_channel_perms=None,
                 premium_label=None, str_ids=False, counts_as_setting=None) -> PanelNode:
    """channel_select leaf storing a single channel id (``multi=False``) or a list.

    ``str_ids=True`` stores ids as strings (see ``_id_accessors``).
    ``counts_as_setting=False`` excludes the leaf from the category's
    "N of M configured" badge (for optional tuning, e.g. disabled-channel lists)."""
    g, s, c = _id_accessors(path, multi=multi, as_str=str_ids)
    return PanelNode(
        key=key, label=label, kind="channel_select", description=description,
        channel_types=channel_types, get_values=g, set_values=s, clear_values=c,
        min_values=0, max_values=(max_values if multi else 1),
        required_channel_perms=required_channel_perms,
        premium_label=premium_label, counts_as_setting=counts_as_setting,
    )


def option_leaf(key, path, *, label, options, description="", multi=False, max_values=25,
                premium_label=None, premium_values=None) -> PanelNode:
    """option_select leaf storing a single value (``multi=False``) or a list."""
    async def _get(guild_id):
        if multi:
            return [str(v) for v in await get_config_list(guild_id, path)]
        v = await get_config_field(guild_id, path)
        return [str(v)] if v not in (None, "") else []

    async def _set(guild_id, values):
        if multi:
            return await set_config_list(guild_id, path, [str(v) for v in values])
        if values:
            return await set_config_field(guild_id, path, str(values[0]))
        return await clear_config_field(guild_id, path)

    return PanelNode(
        key=key, label=label, kind="option_select", description=description,
        options=options, get_values=_get, set_values=_set,
        min_values=1, max_values=(max_values if multi else 1),
        premium_values=premium_values, premium_label=premium_label,
    )


def bool_leaf(key, path, *, label, description="", true_label="Enabled",
              false_label="Disabled", premium_label=None) -> PanelNode:
    """option_select leaf storing a real Python bool at ``path`` (a two-choice picker).

    Use for a standalone on/off setting that is NOT a menu's own toggle (menus use
    ``menu_group(toggle_path=...)``). Stores a true ``bool`` so downstream ``if flag:`` checks
    behave - unlike ``option_leaf``, which would persist the string ``"True"``/``"False"``.
    """
    async def _get(guild_id):
        return ["true" if await get_config_field(guild_id, path) else "false"]

    async def _set(guild_id, values):
        return await set_config_field(guild_id, path, bool(values and values[0] == "true"))

    return PanelNode(
        key=key, label=label, kind="option_select", description=description,
        options=[("true", true_label, ""), ("false", false_label, "")],
        get_values=_get, set_values=_set,
        min_values=1, max_values=1,
        premium_label=premium_label,
    )


def text_leaf(key, path, *, label, description="", placeholder="", min_length=0,
              max_length=1000, paragraph=False, modal_title="", validator=None,
              premium_label=None) -> PanelNode:
    """modal_input leaf storing a free-text string at ``path`` (optional ``validator``)."""
    async def _get(guild_id):
        v = await get_config_field(guild_id, path)
        return [str(v)] if v not in (None, "") else []

    async def _set(guild_id, values):
        if values and str(values[0]).strip():
            return await set_config_field(guild_id, path, values[0])
        return await clear_config_field(guild_id, path)

    async def _clear(guild_id):
        return await clear_config_field(guild_id, path)

    return PanelNode(
        key=key, label=label, kind="modal_input", description=description,
        get_values=_get, set_values=_set, clear_values=_clear,
        modal_title=modal_title or f"Set {label}", modal_label=label,
        modal_placeholder=placeholder, modal_min_length=min_length,
        modal_max_length=max_length, modal_paragraph=paragraph, modal_required=False,
        modal_validator=validator, premium_label=premium_label,
    )


def int_leaf(key, path, *, label, description="", minimum=None, maximum=None,
             modal_title="", premium_label=None) -> PanelNode:
    """modal_input leaf storing an integer at ``path`` (range-validated)."""
    def _validate(raw: str):
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            return False, None, "Please enter a whole number."
        if minimum is not None and n < minimum:
            return False, None, f"Must be at least {minimum}."
        if maximum is not None and n > maximum:
            return False, None, f"Must be at most {maximum}."
        return True, n, ""

    async def _get(guild_id):
        v = await get_config_field(guild_id, path)
        return [str(v)] if v is not None else []

    async def _set(guild_id, values):
        if values and str(values[0]).strip() != "":
            return await set_config_field(guild_id, path, int(values[0]))
        return await clear_config_field(guild_id, path)

    async def _clear(guild_id):
        return await clear_config_field(guild_id, path)

    return PanelNode(
        key=key, label=label, kind="modal_input", description=description,
        get_values=_get, set_values=_set, clear_values=_clear,
        modal_title=modal_title or f"Set {label}", modal_label=label,
        modal_validator=_validate, modal_min_length=1, modal_max_length=20,
        modal_required=False, premium_label=premium_label,
    )


def float_leaf(key, path, *, label, description="", minimum=None, maximum=None,
               modal_title="", premium_label=None) -> PanelNode:
    """modal_input leaf storing a float at ``path`` (range-validated).

    The decimal sibling of ``int_leaf`` - use for multipliers / rates (e.g. an XP
    bonus of ``1.15``) where a whole number is too coarse.
    """
    def _validate(raw: str):
        try:
            n = float(str(raw).strip())
        except (TypeError, ValueError):
            return False, None, "Please enter a number (decimals allowed)."
        if minimum is not None and n < minimum:
            return False, None, f"Must be at least {minimum}."
        if maximum is not None and n > maximum:
            return False, None, f"Must be at most {maximum}."
        return True, n, ""

    async def _get(guild_id):
        v = await get_config_field(guild_id, path)
        return [str(v)] if v is not None else []

    async def _set(guild_id, values):
        if values and str(values[0]).strip() != "":
            return await set_config_field(guild_id, path, float(values[0]))
        return await clear_config_field(guild_id, path)

    async def _clear(guild_id):
        return await clear_config_field(guild_id, path)

    return PanelNode(
        key=key, label=label, kind="modal_input", description=description,
        get_values=_get, set_values=_set, clear_values=_clear,
        modal_title=modal_title or f"Set {label}", modal_label=label,
        modal_validator=_validate, modal_min_length=1, modal_max_length=20,
        modal_required=False, premium_label=premium_label,
    )


def int_list_leaf(key, path, *, label, description="", minimum=None, maximum=None,
                  modal_title="", premium_label=None) -> PanelNode:
    """modal_input leaf storing a list of ints, entered/shown as a comma-separated list
    (e.g. ``10, 25, 50``). Empty input clears the list. Round-trips cleanly: the current
    value is pre-filled as the same comma-separated form the validator parses."""
    def _validate(raw):
        text = str(raw).strip()
        if not text:
            return True, [], ""
        out = []
        for part in text.replace(" ", "").split(","):
            if not part:
                continue
            try:
                n = int(part)
            except (TypeError, ValueError):
                return False, None, f"'{part}' is not a whole number."
            if minimum is not None and n < minimum:
                return False, None, f"Values must be at least {minimum}."
            if maximum is not None and n > maximum:
                return False, None, f"Values must be at most {maximum}."
            out.append(n)
        return True, out, ""

    async def _get(guild_id):
        v = await get_config_field(guild_id, path)
        return [", ".join(str(x) for x in v)] if v else []

    async def _set(guild_id, values):
        return await set_config_field(guild_id, path, list(values[0]) if values else [])

    async def _clear(guild_id):
        return await clear_config_field(guild_id, path)

    return PanelNode(
        key=key, label=label, kind="modal_input", description=description,
        get_values=_get, set_values=_set, clear_values=_clear,
        modal_title=modal_title or f"Set {label}", modal_label=label,
        modal_placeholder="e.g. 10, 25, 50, 75, 100",
        modal_validator=_validate, modal_min_length=0, modal_max_length=200,
        modal_required=False, premium_label=premium_label,
    )


def color_leaf(key, path, *, label, description="", modal_title="",
               premium_label=None) -> PanelNode:
    """modal_input leaf storing a color as int, entered/shown as ``#RRGGBB``."""
    async def _get(guild_id):
        c = await get_config_field(guild_id, path)
        return [to_hex(c)] if isinstance(c, int) else []

    async def _set(guild_id, values):
        if values and str(values[0]).strip():
            return await set_config_field(guild_id, path, int(values[0]))
        return await clear_config_field(guild_id, path)

    async def _clear(guild_id):
        return await clear_config_field(guild_id, path)

    return PanelNode(
        key=key, label=label, kind="modal_input", description=description,
        get_values=_get, set_values=_set, clear_values=_clear,
        modal_title=modal_title or f"Set {label}", modal_label=f"{label} (#RRGGBB)",
        modal_validator=hex_validator, modal_min_length=3, modal_max_length=9,
        modal_required=False, premium_label=premium_label,
    )


def dict_editor_leaf(key, path, *, label, description="", key_label="Key",
                     value_label="Value", value_validator=None, max_entries=None,
                     premium_label=None, key_kind="text",
                     key_channel_types=None, value_kind="text",
                     key_validator=None, required_channel_perms=None,
                     value_role_validator=None,
                     counts_as_setting=None) -> PanelNode:
    """dict_editor leaf storing a ``{key: value}`` map at config ``path``.

    ``key_kind="channel"`` picks the key from a ChannelSelect (optionally filtered by
    ``key_channel_types``) and stores it as ``str(channel.id)``; ``value_kind="role"``
    picks the value from a RoleSelect and stores it as ``str(role.id)``, so an admin
    never types a snowflake. ``key_validator`` follows the same
    ``(ok, error_msg, parsed)`` contract as ``value_validator`` and applies to the key
    on every input path. All four default to the original free-text editor.
    ``required_channel_perms`` (with ``key_kind="channel"``) makes every channel key
    pass the same bot-permission check as a channel_select leaf before it is saved.
    ``value_role_validator`` (with ``value_kind="role"``) is an async
    ``(guild, role_id) -> (ok, error_msg)`` business-rule gate on the picked role,
    run after the assignability check (a native RoleSelect cannot exclude roles,
    so cross-setting conflicts are refused here instead).
    ``counts_as_setting=False`` excludes the leaf from the category's
    "N of M configured" badge (for optional tuning, e.g. multiplier maps).
    """
    async def _get(guild_id):
        return dict(await get_config_field(guild_id, path, {}) or {})

    async def _set(guild_id, k, v):
        current = dict(await get_config_field(guild_id, path, {}) or {})
        current[str(k)] = v
        return await set_config_field(guild_id, path, current)

    async def _remove(guild_id, k):
        current = dict(await get_config_field(guild_id, path, {}) or {})
        current.pop(str(k), None)
        return await set_config_field(guild_id, path, current)

    return PanelNode(
        key=key, label=label, kind="dict_editor", description=description,
        dict_get_values=_get, dict_set_value=_set, dict_remove_value=_remove,
        dict_key_label=key_label, dict_value_label=value_label,
        dict_value_validator=value_validator, dict_key_validator=key_validator,
        dict_value_role_validator=value_role_validator,
        dict_max_entries=max_entries,
        dict_key_kind=key_kind, dict_key_channel_types=key_channel_types,
        dict_value_kind=value_kind, required_channel_perms=required_channel_perms,
        premium_label=premium_label,
        counts_as_setting=counts_as_setting,
    )


def grouped_select_leaf(key, path, *, label, groups, items_for, item_value, item_line,
                        item_option_label, description="", page_size=25,
                        premium_label=None) -> PanelNode:
    """grouped_paginated_select leaf storing a single value at config ``path``.

    ``groups() -> list[(value, label)]``; ``items_for(group_value) -> list[item]``.
    """
    async def _get(guild_id):
        v = await get_config_field(guild_id, path)
        return [str(v)] if v not in (None, "") else []

    async def _set(guild_id, values):
        if values:
            return await set_config_field(guild_id, path, str(values[0]))
        return await clear_config_field(guild_id, path)

    return PanelNode(
        key=key, label=label, kind="grouped_paginated_select", description=description,
        get_values=_get, set_values=_set,
        group_get_groups=groups, group_get_items=items_for,
        list_item_value=item_value, list_format_line=item_line,
        list_item_option_label=item_option_label, list_action_label="Select",
        list_page_size=page_size, premium_label=premium_label,
    )
