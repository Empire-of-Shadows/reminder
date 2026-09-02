import type {
  User,
  Guild,
  Channel,
  Role,
  AuditLogPage,
  BumpBot,
  SettingsResponse,
  SettingsPatch,
  GuildSettings,
  GuildBumpStats,
  GuildOverview,
  MemberReminder,
  MyBumpView,
  ScopeGuild,
  DeleteUserDataResponse,
  UserDataSummary,
} from "./types";
import { apiFetch, apiUrl } from "../_engine/api/http";

// Re-export the shared transport surface so pages keep importing from "./api/client".
export {
  UnauthorizedError,
  ApiError,
  TimeoutError,
  discordLoginUrl,
  logoutUrl,
} from "../_engine/api/http";

export const api = {
  // suppressAuthHandler: the "am I logged in?" probe. Public pages (privacy)
  // call this to show login state - a 401 there is a valid answer, not a
  // session expiry, and must not bounce the visitor to /login.
  me: () => apiFetch<User>("/api/me", { suppressAuthHandler: true }),
  guilds: () => apiFetch<Guild[]>("/api/guilds"),
  botInviteUrl: () => apiFetch<{ url: string | null }>("/api/bot-invite-url"),
  bumpBots: () => apiFetch<BumpBot[]>("/api/bump-bots"),

  getChannels: (guildId: string) =>
    apiFetch<Channel[]>(`/api/guilds/${guildId}/channels`),
  getRoles: (guildId: string) =>
    apiFetch<Role[]>(`/api/guilds/${guildId}/roles`),

  settings: (guildId: string) =>
    apiFetch<SettingsResponse>(`/api/guilds/${guildId}/settings`),
  saveSettings: (guildId: string, patch: SettingsPatch) =>
    apiFetch<GuildSettings>(`/api/guilds/${guildId}/settings`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),

  // Everything the dashboard home renders for one server, in one round trip.
  guildOverview: (guildId: string) =>
    apiFetch<GuildOverview>(`/api/guilds/${guildId}/overview`),

  // The bump half of the overview on its own. Kept as a public endpoint - the
  // home page now reads it through /overview, so nothing in the SPA calls this.
  guildBumpStats: (guildId: string) =>
    apiFetch<GuildBumpStats>(`/api/guilds/${guildId}/bump-stats`),

  // Member tier - gated on being IN the server, not on managing it. Each is
  // fetched on its own so one failure never blanks the others.
  memberBumps: (guildId: string) =>
    apiFetch<GuildBumpStats>(`/api/guilds/${guildId}/member/bumps`),
  memberReminder: (guildId: string) =>
    apiFetch<MemberReminder>(`/api/guilds/${guildId}/member/reminder`),

  // The whole member composition in one call - the server page uses this
  // instead of the two above when the reader has no panel access.
  myBumpView: (guildId: string) =>
    apiFetch<MyBumpView>(`/api/guilds/${guildId}/my-bump-view`),

  // Change history, newest first. `before` is the previous page's next_cursor.
  auditLog: (guildId: string, before?: string | null, limit = 50) =>
    apiFetch<AuditLogPage>(
      `/api/guilds/${guildId}/audit-log?limit=${limit}` +
        (before ? `&before=${encodeURIComponent(before)}` : ""),
    ),

  // Privacy page (mirrors TheHost's /api/user/* surface).
  userGuilds: (withData = false) =>
    apiFetch<ScopeGuild[]>(`/api/user/guilds${withData ? "?with_data=true" : ""}`),
  userDataSummary: (guildId?: string | null) =>
    apiFetch<UserDataSummary>(
      guildId
        ? `/api/user/data/summary?guild_id=${encodeURIComponent(guildId)}`
        : "/api/user/data/summary",
    ),
  exportUserDataUrl: (guildId?: string | null) =>
    apiUrl(
      guildId
        ? `/api/user/data/export?guild_id=${encodeURIComponent(guildId)}`
        : "/api/user/data/export",
    ),
  deleteUserData: (guildId?: string | null) =>
    apiFetch<DeleteUserDataResponse>("/api/user/data", {
      method: "DELETE",
      body: JSON.stringify({ confirm: true, guild_id: guildId ?? null }),
    }),
};

/** Build the bot-invite link for a specific guild (explicit click, no popup). */
export function inviteLink(baseUrl: string, guildId: string): string {
  return `${baseUrl}&guild_id=${guildId}`;
}

/** How many servers track each bump bot. Counts only - nothing identifies a server. */
export interface PublicBotCount {
  key: string;
  name: string;
  servers: number;
}

export interface PublicStats {
  servers: number;
  bots_tracked: number;
  /** Servers with a bump channel, a role to ping AND at least one bot chosen.
   *  Optional so a cached older payload from before this field still renders. */
  servers_ready?: number;
  per_bot?: PublicBotCount[];
}

export async function fetchPublicStats(): Promise<PublicStats | null> {
  try {
    const resp = await fetch(apiUrl("/api/stats/public"), { credentials: "omit" });
    if (!resp.ok) return null;
    return (await resp.json()) as PublicStats;
  } catch {
    return null;
  }
}
