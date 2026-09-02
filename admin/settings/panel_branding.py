"""
Admin panel branding template fields.

Every bot that uses the admin framework defines this module with the same
variable names. The engine renders whatever content is provided without
knowing what it represents. Use empty string for unused fields to keep the
interface uniform across bots.

Required fields:
    SETUP_GUIDE_TEXT: Free-form quick-setup guidance shown above the overview.
    PANEL_TITLE:      Title rendered at the top of the master panel.
    PANEL_DESCRIPTION: Short description shown beneath PANEL_TITLE.
    OVERVIEW_FOOTER:  Optional tagline/footer text. Empty string disables it.
"""

SETUP_GUIDE_TEXT = (
    "**Quick Setup Guide**\n"
    "Imperial Reminder watches your server's bump bots and pings you when it's "
    "time to bump again. The minimum setup is two things:\n"
    "\n"
    "**1\\. Bump Channel** - the channel your bump bots post in (and where the "
    "reminder ping will be sent).\n"
    "**2\\. Bump Role** - the role that gets mentioned when a bump is ready.\n"
    "\n"
    "Open **Channels** and **Bump Role** below to set those. Once both are set, "
    "the **Bump Bots** and **Messages** sections unlock.\n"
    "\n"
    "**Supported bots:** Disboard, BumpIt, Bump4You, WeBump, OneBump, Unfocused.\n"
    "Use **Bump Bots → Enabled Bots** to pick which ones to track, and "
    "**Cooldowns** to tune each bot's reminder delay."
)

PANEL_TITLE = "Server Configuration"

PANEL_DESCRIPTION = "Configure Imperial Reminder for this server."

OVERVIEW_FOOTER = ""
