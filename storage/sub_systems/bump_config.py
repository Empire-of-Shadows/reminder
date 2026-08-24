# Python
"""
Bump System Configuration
Constants, bot IDs, delays, keywords, and default structures
"""

from collections import OrderedDict

# Default cooldown Timers (in seconds)
THREE_0 = 30 * 60  # 30 minutes
H1_30 = 90 * 60    # 1 hour 30 minutes
ONE = 60 * 60      # 1 hour
TWO = 2 * 60 * 60  # 2 hours

# Default save structure for guilds
DEFAULT_GUILD_CONFIG = OrderedDict([
    ("enabled_bots", []),
    ("bump_channel", 0),
    ("bump_role", 0),
    ("timers_channel", 0),
    ("timers_message", True),
    ("custom_message", ""),
    ("bot_delay", OrderedDict([
        ("bumpit", ONE),
        ("bump4you", TWO),
        ("disboard", TWO),
        ("webump", TWO),
        ("onebump", TWO),
        ("unfocused", TWO),
    ])),
    ("timestamps", OrderedDict([
        ("bumpit_timestamp", 0),
        ("bump4you_timestamp", 0),
        ("disboard_timestamp", 0),
        ("webump_timestamp", 0),
        ("onebump_timestamp", 0),
        ("unfocused_timestamp", 0),
    ]))
])

# Supported Bump Bots - Bot IDs
DISBOARD_ID = 302050872383242240
BUMPIT_ID = 1006190394415005788
BUMP4YOU_ID = 1089935069927456849
WEBUMP_ID = 1154077045903593555
ONEBUMP_ID = 1028956609382199346
UNFOCUSED_ID = 835255643157168168

# Bot ID to (name, default_delay) mapping
BUMP_BOTS_INFO = {
    DISBOARD_ID: ("disboard", TWO),
    BUMPIT_ID: ("bumpit", ONE),
    BUMP4YOU_ID: ("bump4you", TWO),
    WEBUMP_ID: ("webump", TWO),
    ONEBUMP_ID: ("onebump", TWO),
    UNFOCUSED_ID: ("unfocused", TWO),
}

# Bump success keywords
DISBOARD_KEYWORD = "bump done!"
BUMPIT_SUCCESS_KEYWORD = "bump successful!"
Bump4You = "server bumped successfully"
WEBUMP_SUCCESS = "server successfully bumped"

SUCCESS_KEYWORDS = (
    "bump done",
    "bump successful",
    "bumped successfully",
    "bump carried out",
    "server successfully bumped",
    "successful bump",
    "boop success"
)

# Default cooldown timers (bot_name -> seconds)
BUMP_BOTS = {
    "bumpit": ONE,
    "bump4you": TWO,
    "disboard": TWO,
    "webump": TWO,
    "onebump": TWO,
    "unfocused": TWO,
}

SUPPORTED_BOTS = list(BUMP_BOTS.keys())

# Friendly display names for the bump bots (keys match BUMP_BOTS / SUPPORTED_BOTS).
BOT_DISPLAY_NAMES = {
    "disboard": "Disboard",
    "bumpit": "BumpIt",
    "bump4you": "Bump4You",
    "webump": "WeBump",
    "onebump": "OneBump",
    "unfocused": "Unfocused",
}


# Choices for slash command UI
BUMP_BOTS_CHOICES = {
    "bumpit": {"1 Hour": ONE},
    "bump4you": {"2 Hours": TWO},
    "disboard": {"2 Hours": TWO},
    "webump": {"2 Hours": TWO},
    "onebump": {"2 Hours": TWO, "30 Minutes": THREE_0},
    "unfocused": {"2 Hours": TWO, "90 Minutes": H1_30},
}
