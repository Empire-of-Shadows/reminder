# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Logger factory and the stdlib -> loguru bridge.

``get_logger`` hands back a stdlib :class:`logging.Logger` (call sites rely on the full stdlib
API, e.g. ``logger.isEnabledFor(...)``), while **loguru** is the single sink that actually
renders and writes every record. :class:`InterceptHandler` forwards stdlib records into loguru,
so our own loggers *and* third-party ones (discord.py, pymongo) share one clean, colored,
rotating output. Sinks are configured by ``setup_application_logging`` (see :mod:`.setup`), which
delegates to :func:`_configure_sinks` here.

Naming note: this package is ``log`` (not ``logging``) precisely so ``import logging`` anywhere is
always the stdlib and can never be shadowed by this directory.
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import sys
from typing import Any, Callable, List, Optional, Union

from loguru import logger

# loguru's numeric severities line up with the stdlib for the shared levels
# (DEBUG=10, INFO=20, WARNING=30, ERROR=40, CRITICAL=50), so stdlib ints pass straight through.

# Console format uses loguru colour markup; ``extra[name]`` carries the originating logger name
# and ``extra[ctx]`` the rendered stdlib ``extra=`` fields (both bound by InterceptHandler,
# defaulted via ``logger.configure`` in _configure_sinks).
CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[name]}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>{extra[ctx]}"
)
# File format is the same, sans colour markup.
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{extra[name]}:{function}:{line} - {message}{extra[ctx]}"
)

# ── Console colour behaviour (opt-in via env; files are never coloured) ──────
#
# loguru only colourizes when the sink is a TTY, and inside a Docker container
# stdout/stderr never is one - so production logs viewed over SSH render flat.
# ``LOG_COLOR`` overrides the autodetect for the CONSOLE sink only:
#   force / always / true / 1  -> colourize even without a TTY (docker logs
#                                 pass ANSI through; modern terminals render it)
#   off / never / false / 0    -> never colourize
#   auto / unset               -> today's behaviour (TTY autodetect)
#
# ``LOG_HIGHLIGHT=true`` additionally paints structured tokens inside the message
# itself - ids, amounts, durations, counts, tags, state words, key=value labels -
# so a line breaks into scannable chunks. Purely cosmetic, console-only, and
# any formatting error falls back to the plain format for that record.
#
# The rules below are ONE alternation applied in ONE pass (``_TOKEN_REGEX``):
# at any position the first listed rule that matches wins and the match is
# consumed, so two rules can never nest markup inside each other and the
# injected colour tags are never re-scanned. Order therefore matters only
# where two rules could start at the same character - the specific, labelled
# shapes sit above the generic ones. The vocabulary is fleet-wide (inventoried
# across all six bots 2026-09-01); a rule that never matches in a given bot is
# simply inert there. Token colours are a channel of their own and are chosen
# by KIND, the same in every bot: guild ids yellow, user ids light-blue,
# channel ids light-cyan, message ids light-magenta, roles light-yellow,
# opaque ids (uuids, timer keys) light-green.
_TOKEN_RULES: List[tuple] = [
    # Ecom's compact id convention and its amounts.
    (r"\bG:\d+", "yellow"),
    (r"\bU:\d+", "light-blue"),
    (r"\bC:\d+", "light-cyan"),
    (r"\+[\d,]+ XP\b", "light-green"),
    (r"\+[\d,]+ Embers\b", "light-yellow"),
    # ImperialReminder timer keys ``guild:channel:type:name`` and TheDecree's
    # scheduler key ``key=(guild, channel)``.
    (r"\b\d{15,20}:\d{15,20}:[a-z]+:[a-z0-9_-]+", "light-green"),
    (r"\bkey=\(\d+, ?\d+\)", "light-green"),
    # Labelled ids as the bots write them today: ``guild 123``, ``guild=123``,
    # ``guild_id=123``, ``Guild: 123``, ``gid=123`` and so on. The digit floor
    # keeps small counters (``attempt 1``) out.
    (r"\b(?:guild(?:_id)?|gid)\s*[:=]?\s*\d{5,}", "yellow"),
    (r"\b(?:(?:quoted_|target_|message_)?(?:user|author|actor|member|claimant|reviewer|owner)(?:_id)?)\s*[:=]?\s*\d{5,}", "light-blue"),
    (r"\b(?:channel(?:_id)?|ch|thread(?:_id)?|destination|source)\s*[:=]?\s*\d{5,}", "light-cyan"),
    (r"\b(?:message(?:_id)?|msg(?:_id)?|mid)\s*[:=]?\s*\d{5,}", "light-magenta"),
    (r"\b(?:role(?:_id)?|entitlement)\s*[:=]?\s*\d{5,}", "light-yellow"),
    (r"\b(?:quote_id|claim_id|submission_id|suggestion_id|rule_id)=[0-9a-f-]{8,36}", "light-green"),
    # Bracketed guild-id line prefix ``[123]`` and ``Name (123)`` / ``(ID: 123)`` pairs.
    (r"\[\d{15,20}\]", "yellow"),
    (r"\((?:ID: ?)?\d{15,20}\)", "light-blue"),
    # uuid4 (relay rule ids, codex suggestion and submission ids).
    (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "light-green"),
    # Any remaining bare Discord snowflake.
    (r"\b\d{17,20}\b", "light-blue"),
    # Bracketed word tags: ``[Uno]``, ``[hangman]``, ``[on_message]``, ``[GREETING]``.
    (r"\[[A-Za-z][\w.\- ]{0,24}\]", "light-magenta"),
    # Durations, ratios, percentages, counted nouns.
    (r"\b\d+(?:\.\d+)?\s?(?:ms|s|secs?|seconds?|mins?|minutes?|h|hours?|days?)\b", "light-green"),
    (r"\b\d+/\d+\b", "light-yellow"),
    (r"\b\d+(?:\.\d+)?%", "light-yellow"),
    (r"\b\d+ (?:guilds?|servers?|members?|users?|channels?|messages?|rules?|quotes?|drops?|pages?|tasks?|cogs?|commands?|documents?|docs?|entries|items?|players?|suggestions?|questions?|timers?|bots?|humans?|roles?|records?|games?|schedules?|reminders?|embeds?|attempts?|retries|rows?|keys?|fields?)\b", "light-yellow"),
    # ``#channel-name`` mentions.
    (r"#[a-z][\w-]+", "light-cyan"),
    # Flow arrows.
    (r"(?<=\s)(?:->|=>|\u2192)(?=\s)", "magenta"),
    # Single-quoted names; a possessive (``user's``) is not an opening quote.
    (r"'(?!s\b)[^'\n]{1,60}'", "light-yellow"),
    # Outcome words - green went well, red went wrong, yellow is in flux.
    (r"\b(?:ready|online|started|starting|completed?|success(?:ful(?:ly)?)?|loaded|enabled|connected|resumed|activated|approved|initialized|registered|synced|healthy|granted|created|saved|sent|posted)\b", "green"),
    (r"\b(?:failed|failure|errors?|exceptions?|timeouts?|timed out|cancell?ed|disabled|disconnected|refused|rejected|missing|skipp(?:ed|ing)|denied|expired|not found|withdrawn|invalid|unavailable|degraded|crashed|forbidden|orphaned|stale)\b", "red"),
    (r"\b(?:retry(?:ing)?|pending|waiting|fallback|deprecated|reconnecting|rescheduled|deferred)\b", "yellow"),
    # Any other ``key=`` label, dimmed so the value stands out.
    (r"\b[a-z][a-z0-9_]{1,30}=(?=[^\s=])", "light-black"),
]
_TOKEN_REGEX = re.compile(
    "|".join(f"(?P<t{i}>{pattern})" for i, (pattern, _) in enumerate(_TOKEN_RULES)),
    re.IGNORECASE,
)
_TOKEN_COLORS = {f"t{i}": color for i, (_, color) in enumerate(_TOKEN_RULES)}

# Highlight mode also colours the ``module:function:line`` segment by the
# FEATURE that emitted the record (first case-insensitive substring match on
# the logger name, order matters), so features separate at a glance in a mixed
# tail. The logger name is whatever the bot passed to ``get_logger`` - ecom
# uses dotted module paths (``ecom_system.leveling.sub_system.voice``), the
# other five mostly literal class-style names (``QuoteTimeManager``,
# ``BumpHandler``) - so the keywords below are written against the REAL names
# (fleet inventory 2026-09-01, pinned in the engine test suite), lower-cased,
# with no underscores unless the name has them.
#
# The table carries the whole fleet's vocabulary - each bot only ever matches
# its own names, so entries from other bots are inert. The first block is the
# ordering guards: names that a broader keyword further down would otherwise
# claim for the wrong feature. Anything unmatched keeps the engine's usual
# cyan, which is deliberate - cyan means "engine or third-party plumbing",
# and no storage-engine logger is listed here. A bot can override or extend
# the table without code via ``LOG_SOURCE_COLORS`` in its env:
# ``keyword:color,keyword:color`` - env entries win over this table, and
# color names are validated against loguru's palette so a typo can never
# break the sink.
_SOURCE_COLORS: List[tuple] = [
    # -- Ordering guards (must stay first).
    ("dashboard.activity", "light-black"),  # the per-request line - high volume, dimmed
    ("dashboard", "light-cyan"),            # whole dashboard process; never shares a tail with a bot
    ("voicemanager", "light-red"),          # TheHost Uno voice channels, not ecom voice XP
    ("timerembed", "light-yellow"),         # ImperialReminder countdown embed, not TheCodex embeds
    ("gamestats", "magenta"),               # TheHost cross-game stats, not TheCodex trackers
    # -- Ecom (economy / leveling): dotted paths under ecom_system.* plus a few literals.
    ("voice", "blue"),
    ("reaction", "magenta"),
    ("sub_system.messages", "green"),
    ("on_message", "green"),
    ("achievement", "yellow"),
    ("prestige", "light-red"),
    ("shop", "light-green"),
    ("trade", "light-green"),
    ("notification", "light-magenta"),
    ("ecom_system.rewards", "light-yellow"),
    ("leveling", "light-blue"),
    ("activity", "light-cyan"),
    ("guild_manager", "white"),
    ("guild_events", "white"),
    ("channel_helper", "white"),
    ("user_settings", "light-white"),
    # -- TheHost (games).
    ("uno", "light-red"),
    ("carddeck", "light-red"),
    ("gamepermissions", "light-red"),
    ("player", "light-red"),
    ("hangman", "light-green"),
    ("tictactoe", "light-blue"),
    ("checkwinner", "light-blue"),
    ("counting", "green"),
    ("milestone", "yellow"),
    ("leaderboard", "light-magenta"),
    ("mastercache", "magenta"),
    ("orphansweep", "magenta"),
    ("optoutgate", "magenta"),
    ("categorycapacity", "magenta"),
    ("cooldown", "magenta"),
    ("privacy", "white"),
    ("eviction", "white"),
    # -- TheCodex.
    ("drop", "light-blue"),
    ("wyr", "magenta"),
    ("suggestion", "light-green"),
    ("guide", "green"),
    ("greeting", "light-magenta"),
    ("whitelist", "light-magenta"),
    ("guildevent", "light-magenta"),        # codex GuildEventHandler (screening); host GuildEvents
    ("member", "light-magenta"),
    ("embed", "yellow"),
    ("colorset", "yellow"),
    ("colortier", "yellow"),
    ("tracker", "light-cyan"),
    ("announcement", "light-red"),
    ("board", "blue"),                      # after leaderboard and dashboard, on purpose
    # -- TheDecree: the specific Quote* loggers first, ``quote`` is the family fallback.
    ("quotetime", "blue"),
    ("quotecommands", "light-magenta"),
    ("quoteview", "light-blue"),
    ("quotelibrary", "yellow"),
    ("quote", "magenta"),
    ("image", "light-red"),
    # -- ImperialReminder.
    ("bump", "green"),
    ("timehandler", "blue"),
    ("lifecycle", "magenta"),
    # -- Stygian-Relay: the specific forwarding loggers first, ``forward`` is the hot path.
    ("forwardingactions", "light-blue"),
    ("rule_schema", "magenta"),
    ("forward.view", "light-green"),
    ("forward", "green"),
    ("guildmanager", "light-red"),
    ("relay.guild", "yellow"),
    ("startup.bot", "light-magenta"),
    ("idle", "light-black"),
    # -- Shared subsystems (every bot).
    ("premium", "light-yellow"),
    ("ipc", "light-cyan"),
    ("errorhandler", "red"),
    ("auditlog", "white"),
    ("admin", "white"),
    ("panelflow", "white"),
    ("gatekeeper", "white"),
    ("presencerotator", "light-black"),
    ("main", "light-white"),
]
_SOURCE_DEFAULT_COLOR = "cyan"

# loguru's colour palette - the only names LOG_SOURCE_COLORS may use.
_VALID_COLORS = frozenset(
    ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
    + ["light-" + c for c in ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")]
)

# Resolved at sink-configure time: env overrides first, then the fleet table.
_ACTIVE_SOURCE_COLORS: List[tuple] = list(_SOURCE_COLORS)


def _env_source_colors() -> List[tuple]:
    """Parse LOG_SOURCE_COLORS (``keyword:color,...``); invalid entries dropped."""
    out: List[tuple] = []
    for part in (os.getenv("LOG_SOURCE_COLORS") or "").split(","):
        keyword, _, color = part.partition(":")
        keyword, color = keyword.strip().lower(), color.strip().lower()
        if keyword and color in _VALID_COLORS:
            out.append((keyword, color))
    return out


def _resolve_source_colors() -> None:
    global _ACTIVE_SOURCE_COLORS
    _ACTIVE_SOURCE_COLORS = _env_source_colors() + _SOURCE_COLORS

# Level colours applied at sink setup (console rendering only - markup is
# stripped wherever colourize is off, and files never colourize). WARNING
# (yellow) and ERROR (red) keep loguru's defaults; INFO gains green and DEBUG
# blue so levels separate on a scan. The plain console format paints the whole
# message body in the level colour; highlight mode keeps that only for WARNING
# and above (see ``_highlighted_console_format``).
_LEVEL_COLORS = {
    "INFO": "<green><bold>",
    "DEBUG": "<blue>",
}

def _apply_level_colors() -> None:
    for level_name, color in _LEVEL_COLORS.items():
        try:
            logger.level(level_name, color=color)
        except Exception:
            # A level colour is cosmetic; never let it break sink setup.
            pass


def _source_color(logger_name: str) -> str:
    lowered = logger_name.lower()
    for key, color in _ACTIVE_SOURCE_COLORS:
        if key in lowered:
            return color
    return _SOURCE_DEFAULT_COLOR


def _console_colorize() -> Optional[bool]:
    """Resolve LOG_COLOR: True (force), False (off), or None (TTY autodetect)."""
    value = (os.getenv("LOG_COLOR") or "auto").strip().lower()
    if value in ("force", "always", "true", "1", "yes", "on"):
        return True
    if value in ("off", "never", "false", "0", "no"):
        return False
    return None


def _highlight_enabled() -> bool:
    return (os.getenv("LOG_HIGHLIGHT") or "").strip().lower() in ("1", "true", "yes", "on")


def _colorize_tokens(text: str) -> str:
    """Wrap every ``_TOKEN_RULES`` match in ``text`` with its colour markup, in one pass."""
    return _TOKEN_REGEX.sub(
        lambda m: f"<{_TOKEN_COLORS[m.lastgroup]}>{m.group(0)}</{_TOKEN_COLORS[m.lastgroup]}>",
        text,
    )


def _highlighted_console_format(record: dict) -> str:
    """Dynamic console format that wraps known tokens in colour markup.

    The message text (plus the rendered ``extra=`` context) is embedded literally
    into the returned format string, so braces are doubled and ``<`` escaped first
    (or loguru would parse stray markup out of user content); the colour tags
    injected AFTER that escaping are the only markup loguru sees, and because the
    tokenizer is a single-pass alternation the injected tags are never re-scanned.
    WARNING and above keep the level colour on the message body (tokens are
    painted inside it); INFO and DEBUG bodies stay neutral so the tokens carry the
    colour. When format is a callable, loguru appends neither the newline nor the
    exception - both are included explicitly.
    """
    try:
        raw = record["message"] + str(record["extra"].get("ctx", ""))
        msg = raw.replace("{", "{{").replace("}", "}}").replace("<", r"\<")
        msg = _colorize_tokens(msg)
        if record["level"].no >= logging.WARNING:
            msg = "<level>" + msg + "</level>"
        src = _source_color(str(record["extra"].get("name", "")))
        prefix = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            f"<{src}>{{extra[name]}}</{src}>:<{src}>{{function}}</{src}>:"
            f"<{src}>{{line}}</{src}> - "
        )
        return prefix + msg + "\n{exception}"
    except Exception:
        return CONSOLE_FORMAT + "\n{exception}"

# Noisy third-party loggers we pin to WARNING so the console stays readable.
_NOISY_LOGGERS = (
    "discord",
    "discord.gateway",
    "discord.client",
    "discord.http",
    "pymongo",
    "pymongo.connection",
    "pymongo.serverSelection",
    "pymongo.topology",
    "motor",
)


def _resolve_log_level(value: Any, default: int = logging.INFO) -> int:
    """Coerce an int / level-name string (e.g. ``"DEBUG"``) into a logging level int.

    Falls back to ``default`` for empty/unknown names so a bad ``LOG_LEVEL`` can never yield a
    non-int that would break ``setLevel``.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        resolved = logging.getLevelName(value.strip().upper())
        return resolved if isinstance(resolved, int) else default
    return default


# Shared default level (LOG_LEVEL env wins). Consulted by presets and set_global_level.
_GLOBAL_LOG_LEVEL: int = _resolve_log_level(os.getenv("LOG_LEVEL"), logging.INFO)

# Ids of the loguru sinks we added, plus the args used, so set_global_level can reconfigure them.
_SINK_IDS: List[int] = []
_STATE: dict = {}


# Attributes every stdlib LogRecord carries; anything else on a record was passed by the
# call site through ``logger.info(..., extra={...})`` and is context worth keeping.
_STD_RECORD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "taskName"}


def _record_context(record: logging.LogRecord) -> tuple:
    """Split the call site's ``extra=`` fields off a stdlib record.

    Returns ``(fields, rendered)``: the raw field dict (bound into loguru's ``extra`` so the JSON
    sink keeps it structured) and its ``" | k=v k=v"`` rendering for the text sinks (empty when
    there is nothing to show; ``None`` values are skipped). Before 2026-09-01 the bridge dropped
    these fields entirely, so a line like TheHost's ``"Start command invoked"`` rendered with no
    guild or channel at all.
    """
    fields = {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STD_RECORD_ATTRS and not key.startswith("_")
    }
    pairs = [f"{key}={value}" for key, value in fields.items() if value is not None]
    return fields, (" | " + " ".join(pairs) if pairs else "")


class InterceptHandler(logging.Handler):
    """Forward stdlib logging records into loguru (the single rendering sink).

    The standard loguru bridge: every record emitted through the stdlib - our ``get_logger``
    loggers as well as third-party libraries - is re-emitted through loguru so it inherits the
    shared format, colours, rotation and retention. Call-site ``extra=`` fields ride along as
    ``extra[ctx]`` (text sinks) and ``extra[fields]`` (JSON sink).
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Map the stdlib level to a loguru level name when possible; else fall back to the number.
        try:
            level = logger.level(record.levelname).name
        except (ValueError, KeyError):
            level = record.levelno

        # Walk out of the logging machinery so {function}/{line} point at the real caller.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        fields, ctx = _record_context(record)
        logger.opt(depth=depth, exception=record.exc_info).bind(
            name=record.name, ctx=ctx, fields=fields
        ).log(level, record.getMessage())


def _install_intercept(level: int = 0) -> None:
    """Make the stdlib root funnel everything into loguru (root captures at level 0)."""
    logging.basicConfig(handlers=[InterceptHandler()], level=level, force=True)


def _ensure_intercept() -> None:
    """Install the intercept lazily so ``get_logger`` works even before setup is called."""
    root = logging.getLogger()
    if not any(isinstance(h, InterceptHandler) for h in root.handlers):
        _install_intercept()


def _silence_noisy_loggers(level: int = logging.WARNING) -> None:
    """Pin chatty third-party loggers to WARNING for a readable console."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)


def _configure_sinks(
    app_name: str,
    log_dir: str = "logs",
    level: int = logging.INFO,
    *,
    console: bool = True,
    file: bool = True,
    json: bool = True,
    backtrace: bool = True,
    diagnose: bool = False,
) -> int:
    """Reset loguru and install our console / file / JSON sinks, then wire the stdlib intercept.

    Replaces the old per-logger handlers, ``RotatingFileHandler`` and ``cleanup_old_logs``:
    loguru owns rotation (``10 MB``) and retention (``10 days``). Returns the resolved level.
    """
    global _SINK_IDS, _STATE

    os.makedirs(log_dir, exist_ok=True)

    # Drop every existing sink (including loguru's default stderr handler) and set a default
    # ``name`` extra so the format's {extra[name]} always resolves for un-bound records.
    logger.remove()
    logger.configure(extra={"name": app_name, "ctx": "", "fields": {}})
    _apply_level_colors()
    _resolve_source_colors()

    ids: List[int] = []
    if console:
        console_format: Union[str, Callable] = CONSOLE_FORMAT
        if _highlight_enabled():
            console_format = _highlighted_console_format
        console_kwargs: dict = {}
        colorize = _console_colorize()
        if colorize is not None:
            console_kwargs["colorize"] = colorize
        ids.append(
            logger.add(
                sys.stderr,
                level=level,
                format=console_format,
                backtrace=backtrace,
                diagnose=diagnose,
                **console_kwargs,
            )
        )
    if file:
        ids.append(
            logger.add(
                os.path.join(log_dir, f"{app_name}.log"),
                level=level,
                format=FILE_FORMAT,
                rotation="10 MB",
                retention="10 days",
                encoding="utf-8",
                enqueue=True,
                backtrace=backtrace,
                diagnose=diagnose,
            )
        )
    if json:
        ids.append(
            logger.add(
                os.path.join(log_dir, f"{app_name}.jsonl"),
                level=level,
                serialize=True,
                rotation="10 MB",
                retention="10 days",
                encoding="utf-8",
                enqueue=True,
            )
        )

    _SINK_IDS = ids
    _STATE = dict(
        app_name=app_name,
        log_dir=log_dir,
        console=console,
        file=file,
        json=json,
        backtrace=backtrace,
        diagnose=diagnose,
    )
    _install_intercept()
    return level


def set_global_level(level: Any) -> int:
    """Set the shared level. Reconfigures live sinks if logging has already been set up."""
    global _GLOBAL_LOG_LEVEL
    _GLOBAL_LOG_LEVEL = _resolve_log_level(level)
    if _STATE:
        _configure_sinks(level=_GLOBAL_LOG_LEVEL, **_STATE)
    return _GLOBAL_LOG_LEVEL


def get_logger(module_name: str, level: Optional[int] = None) -> logging.Logger:
    """Return a stdlib :class:`logging.Logger` for ``module_name``.

    A thin handle: it carries no handlers of its own and funnels into loguru through the root
    :class:`InterceptHandler`. All output configuration (console/file/JSON, rotation, retention,
    colours) lives centrally in :func:`setup_application_logging`. Prefer ``get_logger(__name__)``.
    """
    _ensure_intercept()
    log = logging.getLogger(module_name)
    if level is not None:
        log.setLevel(level)
    return log
