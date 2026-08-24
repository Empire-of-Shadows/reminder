# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Imperial Reminder** is a Discord bot that tracks and reminds users when it's time to bump their server on Discord server-listing services (Disboard, BumpIt, Bump4You, WeBump, OneBump, Unfocused). It monitors bump success messages, schedules reminders based on cooldown periods, and manages guild-specific configuration in MongoDB. A FastAPI web dashboard lets server admins configure the bot via Discord OAuth.

ImperialReminder is fully aligned with the **shared Empire of Shadows engine architecture** (same standard as TheDecree, TheCodex, and Stygian-Relay): all four shared engines are vendored and drift-gated, with thin bot-owned seams. See the monorepo-root `../../CLAUDE.md` for the ecosystem-wide rules; this file wins on local details.

## Vendored engines - never edit the copies

Four engine masters in `EmpireSystems/` are vendored into this repo. Files carrying a `VENDORED ... DO NOT EDIT HERE` banner are generated - edit the master and re-run the sync tool **from the monorepo root, always with `--bot reminder`**:

| Engine | Vendored into | Sync tool | Bot-owned seam |
|---|---|---|---|
| storage_engine | `storage/` (48 files) | `python EmpireSystems/tools/sync_storage_engine.py --bot reminder` | `storage/settings/{bindings,collections}.py`, `config_manager.py`, `audit_log.py`, `setup_gatekeeper.py`, `sub_systems/` |
| admin_engine | `admin/` (33 files) | `python EmpireSystems/tools/sync_admin_engine.py --bot reminder` | `admin/settings/{bindings,panel_configs,panel_branding}.py` |
| runtime_engine | `health_endpoint.py`, `startup/{phases,loader,presence}.py`, `utils/env.py` | `python EmpireSystems/tools/sync_runtime_engine.py --bot reminder` | `startup/bot.py`, `startup/sync.py` |
| dashboard_engine | `dashboard/_engine/`, `dashboard/frontend/src/_engine/` | `python EmpireSystems/tools/sync_dashboard_engine.py --bot reminder` | `dashboard/config.py`, `db.py`, `app.py`, `auth/{dependencies,panel_role}.py`, `routers/`, `services/` |

Drift is gated with each tool's `--check --bot reminder`; all four report a real green (no `[PENDING-MIGRATION]`).

"Not set up yet" messages come from the engine `admin/setup_notice.py` - never hand-write one. Besides the panel breadcrumb it names WHO can open the panel, which on a fresh guild is only the owner and Manage Server holders. This bot's node is a top-level leaf named **Panel Access Roles** rather than the engine's default "Role Configuration" menu, so `admin/settings/bindings.py` sets `ROLE_ACCESS_PATH` to override the breadcrumb. Both consumers (the bump handler's unconfigured-bump nudge and the `check_or_notify` gate) go through it; the gate imports it lazily because `admin/__init__` pulls the panel engine, which reads back into storage.

## Running the Bot

### Local Development

```bash
pip install -r requirements.txt

# Environment via docker/.env (preferred; docker/.env.local dev override wins).
# Required: DISCORD_TOKEN (or TOKEN), MONGO_URI

python Reminder.py            # bot (health on 50014)
python -m dashboard.app       # dashboard (separate process, port 54014)
```

### Docker Deployment

Docker assets live in `docker/`. `./reminder.sh` (in `docker/`) backs up images, rebuilds both services, polls health, and rolls back on failure. Bot health on **50014**, dashboard on **54014**; both on the external `obsidian_grid` network.

## Architecture

### Entry Point and Lifecycle (`Reminder.py`)

1. Load `docker/.env` (+ `.env.local` override), `setup_application_logging` (loguru via `storage.log`).
2. `_async_main()`: signal handlers -> `db_manager.initialize()` -> health server (vendored runtime_engine endpoint, `bot_name="ImperialReminder"`; returns **503 unhealthy** when the DB is down, no recon fields) -> `start_services()` races `bot.start()` against a shutdown event.
3. `on_ready()` (idempotent via `bot._init_done`), phases in order: Database Attachment -> Cog Loading -> Command Sync -> Status Setup -> Timer Reschedule -> Background Tasks (idle rotation). On reconnect only presence refreshes.
4. `shutdown_handler()` order matters: health server -> cancel + await background tasks (TimerHandler `active_timers`, BumpHandler batch tasks, idle rotation) -> `bot.close()` -> `db_manager.close()` LAST (cog teardown may touch the DB). Bump timers are safe to drop - they rebuild from stored timestamps on boot.

### Bot Instance (`startup/bot.py`)

Slash-only: `command_prefix=commands.when_mentioned`, no prefix commands anywhere. Lean intents: `Intents.none()` + `guilds` + `guild_messages` + `message_content` (needed to read bump bots' messages). Constructor `AllowedMentions(everyone=False, roles=False, users=False)`; the reminder sender re-enables ONLY the configured bump role per send.

### Startup Seam (`startup/sync.py`)

Thin seam over the vendored `startup/loader.py`: `COG_DIRECTORIES = ["./commands", "./admin", "./Features"]` + `attach_databases()`. Auto-discovery: any `.py` under those roots defining `async def setup(bot)` is loaded - drop a file, no manual list.

`attach_databases()` initializes and attaches, in order:

| Attribute | Source | Purpose |
|---|---|---|
| `bot.db_manager` | `storage.settings.collections` | engine DatabaseManager (must init first) |
| `bot.audit_log` | `storage.audit_log` | engine AuditLog over the TTL'd `audit_log` collection |
| `bot.guild_config_manager` | `storage.config_manager` | typed wrapper over engine GuildConfigStore |
| `bot.setup_gatekeeper` | `storage.setup_gatekeeper` | engine SetupGate (bump channel + role required) |
| `bot.timer_handler` | `Features.time_handler.TimerHandler` | reminder scheduling (SINGLETON) |
| `bot.idle_manager` | `Features.idle.IdleManager` | presence rotation (engine PresenceRotator seam) |

### Storage Layer (`storage/`)

- **Seam** `storage/settings/collections.py`: the collection registry (`settings_guild_data` = live guild config + bump timestamps in DB `ImperialReminder`; TTL'd `audit_log`) passed as `collection_configs=` to the engine base. `db_manager` is imported as `from storage.settings.collections import db_manager`. (The engine premium collections and the raw `get_collection`/`db_client` accessors were removed 2026-08-24 with premium itself; migration m2 cleans the stored collections.)
- **`config_manager.py`**: `GuildConfig` dataclass (typed domain access) + `GuildConfigManager`, a thin wrapper over the engine `GuildConfigStore` (`id_field="_id"`, 30s cache TTL bounding cross-process staleness vs the dashboard). Every write is a surgical dotted `$set` - never a full-document replace. `peek()` gives sync display-only access; `invalidate()` drops a guild's cache.
  ```python
  config = await bot.guild_config_manager.get_config(guild_id)
  if not config.bump_channel or not config.bump_role:
      return
  await bot.guild_config_manager.set_value(guild_id, "timestamps.disboard_timestamp", int(time.time()))
  ```
  `GuildConfig` fields: `enabled_bots`, `bump_channel`, `bump_role`, `timers_channel`, `timers_message`, `custom_message`, `roles` (panel access lists), `bot_delay`, `timestamps`, `extra_data` (dynamic keys like `timer_message_{channel_id}`). (The `premium` dict was removed 2026-08-24; the key stays listed in `from_dict`'s standard set so stored docs are ignored, not adopted into `extra_data`, until migration m2 unsets them.)
- **`sub_systems/bump_config.py`**: bump-bot constants (`BUMP_BOTS_INFO`, `BUMP_BOTS`, `SUCCESS_KEYWORDS`, ...).
- Logging: `from storage.log import get_logger, setup_application_logging` (loguru engine subsystem). The old `storage/logging/` and `utils/logger.py` are gone.

### TimerHandler (`Features/time_handler.py`)

Production-grade scheduler for all reminders. **One instance** created in `attach_databases()` at `bot.timer_handler` - never create another (duplication breaks cancellation and remaining-time math). Monotonic time; jitter; exponential-backoff retries; callback timeouts; dedup via `replace_if_sooner_than`; scope cancellation; pause/resume. Timer ID: `{guild_id}:{channel_id}:{timer_type}:{name}`. Bot-owned by policy (sole consumer fleet-wide) - do not promote.

### BumpHandler (`Features/bump/detection/handler.py`)

Detects bump-success messages via **two listeners**: `on_message` and `on_message_edit` (WeBump edits ~1s after an empty message - handled by force-refetch on edit). `extract_all_text` aggregates embeds/content/components/attachments/stickers with a refetch fallback and normalization. `_resolve_bot_info` matches `author_id`/`webhook_id` against `BUMP_BOTS_INFO` (forgery-resistant: keywords alone never trigger). Success flow: save timestamp (dotted `$set`) -> compute timers -> schedule embed update -> schedule reminder. Reminders batch in a 10s window per channel (`channel_tasks`, cancelled in `cog_unload` AND at shutdown); a written `custom_message` replaces the standard wording (every feature is free - premium was removed 2026-08-24, and the old premium-only webhook delivery path went with it since nothing could ever configure it); sends use an explicit `AllowedMentions` that allows ONLY the bump role.

### Premium: removed (2026-08-24)

ImperialReminder is 100% free. The `commands/premium/` package, the engine `PremiumManager` attach, the panel Premium section, the dashboard premium surfaces, and the `PREMIUM_*` env vars are all gone; `bindings.is_premium` remains only because the vendored engine imports it by name, and it returns True. The vendored `storage/premium/` engine files remain (byte-identical fleet-wide) but nothing constructs them. Stored premium data (`entitlements`, `premium_state`, `bot_settings`, the config `premium` dict) is cleaned by migration m2.

### Admin Panel (`admin/`)

Vendored admin_engine at the bot root; seam in `admin/settings/`. `MAIN_PANEL` tree: Core Setup (bump channel/role, timers channel) and Panel Access Roles (a top-level LEAF per ADMIN_PANEL_STANDARD 1.1 - engine `panel_roles_pair(include_mod=False, str_ids=True)` writing `roles.admin_role_ids`, the same list the dashboard reads, gated by the builder's default `manage_guild_pre_check`) in the `main` group, then Bump Bots (enabled bots, per-bot cooldowns), Messages (custom message, timer embed) in the `feature` group.

The panel is **ADMIN-ONLY**: `bindings.resolve_panel_role` delegates to the engine `resolve_panel_role_from_config` (Manage Server OR `roles.admin_role_ids`) and collapses anything else to "none". There is no Mod tier, no `roles.mod_role_ids` key, and no `PanelNode.mod_allowed` flags in the seam. (The vendored engine still carries mod machinery for the bots that have not converted - leave it alone.)

### Dashboard (`dashboard/`)

FastAPI backend + React 19/TS/Vite SPA, on the shared dashboard_engine (`_engine/` backend: csrf/oauth/session/signing/panel_access/rate_limit/discord_cache; `frontend/src/_engine/`: EcosystemNav, formatError, eos-tokens, shared components). Shared GateKeeper SSO (identical `GATEKEEPER_*`, `DASHBOARD_SECRET_KEY`, `eos_session` cookie across all dashboards; `SHARED_SESSIONS_URI` -> `WebSessions.SharedSessions`).

- Seam config keys in `config.py`: `RATE_LIMITS`, `OAUTH_REDIRECT_ALLOWLIST`, `OAUTH_DEFAULT_REDIRECT`, `ADMINISTRATOR_PERMISSION`, env-driven `TRUSTED_PROXY_IPS` (set behind a reverse proxy or proxied visitors share one rate bucket).
- `auth/panel_role.py` is a thin 2-tier policy (admin/none) over `_engine/auth/panel_access.py`: MANAGE_GUILD verified LIVE on access-gated routes; guild-list probes use `verify_manage_live=False`. There is no Mod tier - `roles.admin_role_ids` is the only configured grant, and every dashboard route is admin-only.
- Settings PUT: whitelisted surgical dotted `$set` only (never a full-document write - the bot writes timestamps concurrently) and validates channel/role ids belong to the guild.
- Discord API reads (bot guilds, bot id, channels, roles) go through the engine `_engine/discord_cache.py` (TTL + single-flight + bounded).
- `routers/user_data.py` + `services/user_data.py` back the `/me/privacy` page, mirroring TheHost's `/api/user/*` surface (`/user/guilds?with_data=`, `/user/data/export`, `DELETE /user/data`). ImperialReminder has no per-member tracking, so the only account-linked records are `audit_log` entries naming the actor. Erasure REDACTS the actor identity on audit entries (never drops them - a self-service wipe of the trail would gut the audit log). Both id spellings are matched (int from the admin seam, str from the retired premium cog's historical rows).

## Supported Bump Bots

Configured in `storage/sub_systems/bump_config.py`:

| Bot | ID | Default Cooldown | Shorter Option (free) |
|-----|-----|------------------|------------------|
| Disboard | 302050872383242240 | 2 hours | - |
| BumpIt | 1006190394415005788 | 1 hour | - |
| Bump4You | 1089935069927456849 | 2 hours | - |
| WeBump | 1154077045903593555 | 2 hours | - |
| OneBump | 1028956609382199346 | 2 hours | 30 minutes |
| Unfocused | 835255643157168168 | 2 hours | 90 minutes |

## Common Development Tasks

- **Add a cog**: drop a file with `async def setup(bot)` into `commands/`, `admin/`, or `Features/`. Managers come from `bot.<name>` - never re-instantiate.
- **Add a bump bot**: extend `BUMP_BOTS_INFO`, `BUMP_BOTS`, `DEFAULT_GUILD_CONFIG` delays/timestamps, `SUCCESS_KEYWORDS`, `BUMP_BOTS_CHOICES` in `sub_systems/bump_config.py`.
- **Schema changes**: additive `GuildConfig` fields need no migration (`from_dict` fills defaults). Guild config + bump timestamps are LIVE production data - migrate, never drop. Removing a field ships an idempotent script under `../../TestsAndMigrations/ImperialReminder/migrations/scripts/` (the tree moved out of this repo on 2026-08-08; `_common.py` is the harness: dry run by default, `--apply` to write a backup then `$unset`, `--rollback <file>` to replay it). Run them from `TestsAndMigrations/ImperialReminder/` as `python -m migrations.scripts.<name>`. Run the dry run, read its report, then apply.
- **Engine changes**: edit the master in `EmpireSystems/`, re-run the sync tool with `--bot reminder`, verify `--check`.
- **Debugging detection**: watch `[on_message]` / `[on_message_edit]` / `[extract_all_text]` log lines.

## Important Notes

- **TimerHandler singleton**: exactly one instance at `bot.timer_handler`.
- **Crash recovery**: `Features/start_up.py` reschedules all timers on ready (remaining = `end_time - now`; expired-while-offline fire immediately); `replace_if_sooner_than` makes re-runs safe.
- **Health ports**: bot 50014, dashboard 54014 (`portsRules.md` index 14). Health follows the HealthCheck contract: DB down -> 503 `unhealthy`; Discord disconnected -> 200 `degraded`; never leak internals.
- **MongoDB conventions**: guild IDs as strings (`_id`); timestamps as integer Unix seconds; nested updates via dot notation; surgical `$set` only.
- **Never edit VENDORED-banner files in this repo**; always pass `--bot reminder` to sync tools.

### Environment Variables

Bot: `DISCORD_TOKEN` (or `TOKEN`), `MONGO_URI`.
Dashboard: `GATEKEEPER_CLIENT_ID/SECRET`, `GATEKEEPER_REDIRECT_URI`, `DASHBOARD_SECRET_KEY`, `SHARED_SESSIONS_URI`, `DASHBOARD_HOST`, `DASHBOARD_PORT`, `ENVIRONMENT`, `BASE_URL`, optional `TRUSTED_PROXY_IPS`, `COOKIE_DOMAIN` (prod: `.eosofficial.club`).

## Testing Locally

1. `python Reminder.py`; confirm DB init, managers attached (incl. `idle_manager`), cogs loaded (incl. `admin.admin_cog`), commands synced, health on 50014.
2. `curl http://localhost:50014/health` -> `status: healthy` (stop Mongo -> HTTP 503 `unhealthy`).
3. `/admin panel` -> Core Setup -> set bump channel + role; trigger a real bump; verify `Timer started: {guild_id}:{channel_id}:bump:{bot_name}`.
4. `python -m dashboard.app`; `curl http://localhost:54014/health`.
5. Sync-tool checks: all four `--check --bot reminder` green; dashboard `npm run build` passes.
