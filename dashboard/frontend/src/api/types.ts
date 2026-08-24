import type { Guild as EngineGuild, SessionUser } from "../_engine/api/types";

// Shapes that are the same across the fleet live in the engine. Re-exported here
// so ImperialReminder's own modules keep importing their types from one place.
export type {
  Channel,
  FeatureState,
  FeatureStatus,
  PanelRole,
  Role,
} from "../_engine/api/types";
// Also needed in local scope below - a `export type {...}` re-export does not bind.
import type { FeatureStatus, PanelRole } from "../_engine/api/types";

/** The signed-in user, plus this dashboard's access flags.
 *  The panel is admin-only here, so settings access IS admin access. */
export interface User extends SessionUser {
  can_manage_any: boolean;
  can_access_admin_any: boolean;
  can_access_settings_any: boolean;
}

// The engine leaves panel_role optional because some dashboards omit it.
// ImperialReminder's /api/guilds always sends it, so narrow it back to required.
export interface Guild extends EngineGuild {
  panel_role: PanelRole;
}

/** One cooldown a bump bot offers, exactly as the in-Discord panel offers it. */
export interface BumpBotChoice {
  label: string;
  seconds: number;
}

export interface BumpBot {
  key: string;
  name: string;
  /** The cooldown used when a server has not chosen one. */
  default_cooldown?: number;
  /** Empty or one-item lists mean there is nothing to choose here. */
  choices?: BumpBotChoice[];
}

/** Per-guild bump configuration (mirrors the dashboard settings API).
 * Snowflake IDs are strings ('' = unset) - they exceed JS's safe-integer range. */
export interface PanelRolesConfig {
  admin_role_ids: string[];
}

/** Per-bot cooldown overrides, in seconds, keyed by bump-bot key. */
export type BotDelayConfig = Record<string, number>;

export interface GuildSettings {
  guild_id?: string;
  enabled_bots: string[];
  bump_channel: string;
  bump_role: string;
  timers_channel: string;
  timers_message: boolean;
  custom_message: string;
  roles?: PanelRolesConfig;
  bot_delay?: BotDelayConfig;
  panel_role?: PanelRole;
  [key: string]: unknown;
}

export type SettingsResponse = GuildSettings;

export interface SettingsPatch {
  bump_channel?: string;
  bump_role?: string;
  enabled_bots?: string[];
  timers_channel?: string;
  timers_message?: boolean;
  custom_message?: string;
  roles?: PanelRolesConfig;
  bot_delay?: BotDelayConfig;
}

/** One bump bot's live status within a guild. Unix timestamps in seconds. */
export interface BumpBotStatus {
  key: string;
  name: string;
  last_bump: number | null;
  cooldown: number;
  next_due: number | null;
  status: "ready" | "waiting";
  /** The bump timestamp the last delivered reminder covered (overview only). */
  reminded_for?: number | null;
}

/** A server shown in the privacy page's data-scope picker. `name` is null when
 * the record outlived the user's membership. */
export interface ScopeGuild {
  id: string;
  name: string | null;
  icon: string | null;
}

/** Result of erasing the signed-in user's records, keyed by collection. */
export interface DeleteUserDataResponse {
  user_id: string;
  guild_id: string | null;
  deleted: Record<string, number>;
}

/** How many records name the signed-in user, in the selected scope.
 *  A null count means that collection could not be read - render it as
 *  "could not be counted", never as zero. */
export interface UserDataSummary {
  user_id: string;
  guild_id: string | null;
  audit_log_entries: number | null;
}

export interface GuildBumpStats {
  guild_id: string;
  config_complete: boolean;
  enabled_count: number;
  /** Server's current unix time - anchor client countdowns to avoid clock skew. */
  server_time: number;
  bots: BumpBotStatus[];
}

// ── Guild overview (GET /api/guilds/{id}/overview) ────────────────────────
//
// Every section is independently nullable: the endpoint builds them
// concurrently and nulls out whichever one failed, so one broken collection
// cannot blank the page. Render each null as "could not be loaded", never as
// zero.

/** Live bump state. Extends the /bump-stats shape with the page's roll-ups. */
export interface BumpsOverview extends GuildBumpStats {
  ready_count: number;
  waiting_count: number;
  never_bumped: number;
  /** Soonest cooldown expiry across the enabled bots, unix seconds. */
  next_due: number | null;
  /** Most recent bump across the enabled bots, unix seconds. */
  last_bump: number | null;
  /** Bumps that are off cooldown with no reminder recorded against them. */
  reminders_pending: number;
  now: number;
}

/** What is configured. Snowflakes are strings, '' when unset. */
export interface SetupOverview {
  bump_channel: string;
  bump_role: string;
  timers_channel: string;
  timers_message: boolean;
  custom_message_set: boolean;
  custom_message_length: number;
  admin_role_count: number;
  enabled_bots: string[];
  supported_bots: BumpBot[];
  updated_at: string | null;
  created_at: string | null;
}

/** One day of the change trend. `date` is YYYY-MM-DD in UTC. */
export interface ChangePoint {
  date: string;
  changes: number;
}

export interface ChangeEntry {
  action: string;
  section: string;
  key: string;
  /** Display name of whoever made the change, or null when it was not recorded
   *  (or was redacted from the audit trail on request). */
  actor: string | null;
  at: string | null;
}

export interface ChangesOverview {
  total: number;
  total_30d: number;
  daily: ChangePoint[];
  recent: ChangeEntry[];
}

export interface GuildOverview {
  guild_id: string;
  server_time: number;
  features: FeatureStatus[];
  bumps: BumpsOverview | null;
  setup: SetupOverview | null;
  changes: ChangesOverview | null;
}

// ── Member tier (GET /api/guilds/{id}/member/*) ───────────────────────────
//
// What the server's bump reminder is doing FOR YOU. Fetched additively by the
// dashboard home: each one can fail on its own without costing the others, so
// every consumer treats a missing section as absent, not as empty.

/** Whether the signed-in member is one of the people the reminder pings. */
export interface MemberReminder {
  reminder_role_set: boolean;
  bump_channel_set: boolean;
  bots_tracked: number;
  /** null means "we could not confirm" - the roles lookup came back empty, and
   *  an empty answer cannot be told apart from a failed one. Never render it
   *  as "no". */
  you_will_be_pinged: boolean | null;
  status: "yes" | "no" | "no_role" | "unknown";
}

// ── Audit log (GET /api/guilds/{id}/audit-log) ────────────────────────────

/** One change, folded out of the three shapes the collection actually holds. */
export interface AuditLogRow {
  at: string | null;
  actor: string | null;
  actor_id: string | null;
  source: string;
  section: string;
  key: string;
  action: string;
  old_value: unknown;
  new_value: unknown;
  redacted: boolean;
}

export interface AuditLogSummary {
  total: number;
  window_days: number;
  total_window: number;
  newest: string | null;
}

export interface AuditLogPage {
  entries: AuditLogRow[];
  /** ISO timestamp to pass as `before` for the next page; null at the end. */
  next_cursor: string | null;
  /** First page only, and null when the counts themselves failed. */
  summary?: AuditLogSummary | null;
}
