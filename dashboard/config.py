"""Dashboard configuration - environment variables and constants."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "docker" / ".env")


# Discord OAuth2 - shared GateKeeper bot across the ecosystem.
# Identical GATEKEEPER_* credentials are used by TheHost, TheCodex, EcomBackend
# and ImperialReminder so a single Discord OAuth app powers every dashboard.
DASHBOARD_CLIENT_ID = os.getenv("GATEKEEPER_CLIENT_ID", "")
DASHBOARD_CLIENT_SECRET = os.getenv("GATEKEEPER_CLIENT_SECRET", "")
if not DASHBOARD_CLIENT_ID:
    raise RuntimeError("GATEKEEPER_CLIENT_ID environment variable is required")
if not DASHBOARD_CLIENT_SECRET:
    raise RuntimeError("GATEKEEPER_CLIENT_SECRET environment variable is required")

# ImperialReminder bot token - used to check which guilds the bot is in
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "") or os.getenv("TOKEN", "")
REDIRECT_URI = os.getenv(
    "GATEKEEPER_REDIRECT_URI",
    "http://localhost:54014/auth/discord/callback",
)
DISCORD_API_BASE = "https://discord.com/api/v10"

# MongoDB - ImperialReminder bot data (guild config, etc.).
MONGO_URI = os.getenv("MONGO_URI", "")

# MongoDB - shared session store (WebSessions.SharedSessions + .OAuthStates),
# written by all ecosystem dashboards. Point this at the SAME Mongo the other
# bots use so a login on one dashboard is valid on all of them.
SHARED_SESSIONS_URI = os.getenv("SHARED_SESSIONS_URI", "")

# Session signing (itsdangerous URLSafeTimedSerializer key).
# DASHBOARD_SECRET_KEY must be IDENTICAL across TheHost/TheCodex/EcomBackend/
# ImperialReminder so a cookie set by one service validates on the others.
SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("DASHBOARD_SECRET_KEY environment variable is required")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "eos_session")
SESSION_MAX_AGE_DAYS = int(os.getenv("SESSION_MAX_AGE_DAYS", "30"))

# Cookie domain - set to ".eosofficial.club" in production for cross-subdomain SSO
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").lower() == "production"

# Server
HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "54014"))

# CORS - filter falsy entries so an unset BASE_URL doesn't leak an empty origin.
# Dev origins (Vite/localhost) are gated out of production: with
# allow_credentials=True a stray localhost page must never be a valid origin.
_DEV_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:54014",
    "http://127.0.0.1:54014",
]
CORS_ORIGINS = [
    o
    for o in ([] if IS_PRODUCTION else _DEV_CORS_ORIGINS) + [os.getenv("BASE_URL")]
    if o
]

# Reverse proxies whose X-Forwarded-For header may be trusted for client-IP
# resolution (rate limiting). Comma-separated peer IPs; when the immediate
# peer is not listed, the socket address is used instead so a client cannot
# spoof a fresh rate-limit bucket per request.
TRUSTED_PROXY_IPS = frozenset(
    ip.strip()
    for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",")
    if ip.strip()
)

# Discord permission flags
MANAGE_GUILD_PERMISSION = 0x20
ADMINISTRATOR_PERMISSION = 0x8

# ── Shared dashboard-engine seam values (read by dashboard/_engine/) ──────────
# OAuth redirect allowlist (regex, anchored ^...$) + fallback, used by _engine/auth/oauth.py.
OAUTH_REDIRECT_ALLOWLIST = r"^https?://(localhost(:\d+)?|([a-z0-9-]+\.)?eosofficial\.club)(/.*)?$"
# "/me" is the canonical member home since the 2026-08-31 IA rework; the old
# "/dashboard" address survives only as a client-side redirect to it.
OAUTH_DEFAULT_REDIRECT = "/me"

# Rate-limit route table for _engine/rate_limit.py: (path-prefix, bucket, max, window_s).
# First match wins, so specific prefixes precede their parents. bot-invite-url is
# unauthenticated and triggers bot-token Discord calls on cache miss, so it gets
# its own bucket.
RATE_LIMITS: list[tuple[str, str, int, int]] = [
    ("/auth/discord/callback", "oauth_callback", 10, 60),
    ("/auth/discord", "oauth_start", 20, 60),
    ("/api/me", "me", 100, 60),
    ("/api/stats/public", "public_stats", 30, 60),
    ("/api/bot-invite-url", "bot_invite", 30, 60),
    # Privacy page: export dumps documents and erasure writes them, so both are
    # kept well below what a human clicking the page can produce.
    ("/api/user/data", "user_data", 20, 60),
]


def _validate_config() -> None:
    """Fail fast on missing/misconfigured environment rather than 500ing later.

    The dashboard cannot function without OAuth credentials, the bot token (live
    guild checks), and the Mongo URI. In production, the Secure cookie flag and
    CORS origin also depend on ENVIRONMENT/BASE_URL being set correctly - a
    silent wrong default there is a security regression.
    """
    required = {
        "GATEKEEPER_CLIENT_ID": DASHBOARD_CLIENT_ID,
        "GATEKEEPER_CLIENT_SECRET": DASHBOARD_CLIENT_SECRET,
        "DISCORD_TOKEN": BOT_TOKEN,
        "MONGO_URI": MONGO_URI,
        "SHARED_SESSIONS_URI": SHARED_SESSIONS_URI,
    }
    missing = [name for name, val in required.items() if not val]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    if IS_PRODUCTION:
        if not os.getenv("BASE_URL"):
            raise RuntimeError(
                "BASE_URL must be set in production (used for the CORS origin "
                "and cookie scope)"
            )
        if "localhost" in REDIRECT_URI or "127.0.0.1" in REDIRECT_URI:
            raise RuntimeError(
                "GATEKEEPER_REDIRECT_URI still points at localhost in production"
            )


_validate_config()
