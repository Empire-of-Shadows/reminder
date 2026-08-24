import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, inviteLink } from "../api/client";
import type { Guild, GuildOverview, User } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { KeyValue, Tile } from "../_engine/components/overview/Tile";
import AppHeader from "../components/AppHeader";
import { GuildWebScene } from "../_engine/components/GuildWebScene";
import { formatCountdown, formatRelative } from "../components/overview/format";

/** Real Discord icon for a guild, or null so the scene draws its generated orb.
 *  Typed on the two fields it reads rather than on this bot's Guild, so it also
 *  satisfies the scene's callback, which hands over the wider engine Guild. */
function guildIconUrl(g: { id: string; icon: string | null }): string | null {
  return g.icon ? `https://cdn.discordapp.com/icons/${g.id}/${g.icon}.png?size=64` : null;
}

export default function SettingsHubPage() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [guilds, setGuilds] = useState<Guild[] | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // The scene draws its tether to this element, so the panel has to be a real
  // node in the layout even while it is closed.
  const blobRef = useRef<HTMLElement>(null);

  useEffect(() => {
    api.me().then(setUser).catch(() => {});
    api.guilds().then(setGuilds).catch((e) => setError(formatError(e)));
    api.botInviteUrl().then((r) => setInviteUrl(r.url)).catch(() => {});
  }, []);

  // Client guard: only admins reach Settings; everyone else has no Settings nav
  // link. Server-side routes re-check access on their own.
  useEffect(() => {
    if (user && !user.can_access_settings_any) navigate("/dashboard", { replace: true });
  }, [user, navigate]);

  const webGuilds = useMemo(
    () => (guilds ?? []).filter((g) => g.panel_role !== "none"),
    [guilds],
  );
  const counts = useMemo(() => ({
    total: webGuilds.length,
    admin: webGuilds.filter((g) => g.panel_role === "admin").length,
  }), [webGuilds]);
  const selected = webGuilds.find((g) => g.id === selectedId) ?? null;

  // The blob's live rows. Fetched only when a node is picked, and only once per
  // server - the web can hold a lot of nodes and nobody opens all of them.
  const [overviews, setOverviews] = useState<Record<string, GuildOverview | null>>({});
  const [overviewLoading, setOverviewLoading] = useState(false);
  useEffect(() => {
    if (!selectedId || selectedId in overviews) return;
    const target = selectedId;
    let alive = true;
    setOverviewLoading(true);
    api
      .guildOverview(target)
      .then((o) => {
        if (alive) setOverviews((prev) => ({ ...prev, [target]: o }));
      })
      .catch(() => {
        // null is the "asked and could not answer" marker; the panel says so
        // rather than showing empty rows.
        if (alive) setOverviews((prev) => ({ ...prev, [target]: null }));
      })
      .finally(() => {
        if (alive) setOverviewLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [selectedId, overviews]);

  const message = error ? (
    <div className="alert danger" role="alert">{error}</div>
  ) : !guilds ? (
    <p className="eos-muted">Loading servers...</p>
  ) : webGuilds.length === 0 ? (
    <div className="ov-grid">
      <Tile span={12} quiet title="No manageable servers">
        <p className="ov-body">
          You need Manage Server permission, or a role a manager has granted access to, in a
          Discord server to manage Imperial Reminder there.
        </p>
        {inviteUrl && (
          <div className="admin-actions">
            <a className="btn btn-primary" href={inviteUrl} target="_blank" rel="noreferrer">
              Invite Imperial Reminder to a server
            </a>
          </div>
        )}
      </Tile>
    </div>
  ) : null;

  return (
    <div className="app-layout">
      <AppHeader user={user} />

      <div className="settings-scene">
        {message ? (
          <div className="settings-scene__message">{message}</div>
        ) : (
          <>
            <GuildWebScene
              guilds={webGuilds}
              selectedId={selectedId}
              onSelect={setSelectedId}
              tetherTo={blobRef}
              iconUrl={guildIconUrl}
              hubIcon="/brand/logo-mark.png"
            >
              <span className="gw-eyebrow">Configuration</span>
              <h1 className="gw-title" data-gw-collide>The Web of Servers</h1>
              <p className="gw-sub" data-gw-collide>
                Every server you steward, woven together. Pluck a node to manage it.
              </p>
              <p className="gw-counts">
                {counts.total} servers - {counts.admin} admin
              </p>
            </GuildWebScene>

            <aside
              ref={blobRef}
              className={"gw-blob" + (selected ? " is-show" : "")}
              aria-live="polite"
            >
              {selected && (
                <>
                  <button
                    type="button"
                    className="gw-blob-close"
                    aria-label="Close"
                    onClick={() => setSelectedId(null)}
                  >
                    x
                  </button>
                  <SettingsActionPanel
                    guild={selected}
                    inviteUrl={inviteUrl}
                    overview={
                      selected.id in overviews ? overviews[selected.id] : undefined
                    }
                    overviewLoading={overviewLoading}
                    onNavigate={(path) => navigate(path)}
                  />
                </>
              )}
            </aside>
          </>
        )}
      </div>
    </div>
  );
}

function SettingsActionPanel({
  guild,
  inviteUrl,
  overview,
  overviewLoading,
  onNavigate,
}: {
  guild: Guild;
  inviteUrl: string | null;
  /** undefined = not asked yet, null = asked and could not answer. */
  overview: GuildOverview | null | undefined;
  overviewLoading: boolean;
  onNavigate: (path: string) => void;
}) {
  const iconUrl = guildIconUrl(guild);

  return (
    <>
      <div className="settings-blob__head">
        <div className="guild-icon" style={{ width: 44, height: 44 }}>
          {iconUrl ? <img src={iconUrl} alt="" /> : (guild.name ?? "?")[0]}
        </div>
        <div style={{ minWidth: 0 }}>
          <div
            className="guild-name"
            style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            {guild.name}
          </div>
          <span className="status-badge status-badge--approved">Admin</span>
        </div>
      </div>

      {guild.bot_in_guild && (
        <BlobFacts overview={overview} loading={overviewLoading} />
      )}

      <div className="settings-blob__actions">
        {!guild.bot_in_guild ? (
          inviteUrl && (
            <a
              className="btn btn-primary"
              href={inviteLink(inviteUrl, guild.id)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Invite Imperial Reminder
            </a>
          )
        ) : (
          <>
            <button
              className="btn btn-primary"
              onClick={() => onNavigate(`/settings/${guild.id}`)}
            >
              Settings
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => onNavigate(`/settings/${guild.id}/audit-log`)}
            >
              Change history
            </button>
          </>
        )}
      </div>

      {!guild.bot_in_guild && (
        <p className="guild-invite-hint" style={{ marginTop: 0 }}>
          Bot not in this server yet. Use the link above to add it, then return here.
        </p>
      )}
      {guild.bot_in_guild && !guild.has_config && (
        <p className="guild-invite-hint" style={{ marginTop: 0 }}>
          Not set up yet - open settings to pick a bump channel and reminder role.
        </p>
      )}
    </>
  );
}

/** The few live numbers worth pulling into the node panel. Nothing is shown as
 *  zero when it is really unknown: a failed or missing section says so. */
function BlobFacts({
  overview,
  loading,
}: {
  overview: GuildOverview | null | undefined;
  loading: boolean;
}) {
  if (overview === undefined) {
    return <p className="guild-invite-hint" style={{ marginTop: 0 }}>Loading this server...</p>;
  }
  if (overview === null) {
    return (
      <p className="guild-invite-hint" style={{ marginTop: 0 }}>
        {loading
          ? "Loading this server..."
          : "This server's live status could not be loaded. Settings still open normally."}
      </p>
    );
  }

  const bumps = overview.bumps;
  const changes = overview.changes;

  return (
    <div style={{ margin: "4px 0 12px" }}>
      <KeyValue
        k="Bots tracked"
        v={bumps ? bumps.enabled_count : "Not known"}
      />
      <KeyValue
        k="Ready to bump"
        v={bumps ? bumps.ready_count : "Not known"}
      />
      <KeyValue
        k="Next bump"
        v={
          !bumps
            ? "Not known"
            : bumps.next_due !== null
              ? formatCountdown(bumps.next_due, bumps.now)
              : "Nothing waiting"
        }
      />
      <KeyValue
        k="Last bump"
        v={
          !bumps
            ? "Not known"
            : bumps.last_bump !== null
              ? formatRelative(bumps.last_bump, bumps.now)
              : "None seen yet"
        }
      />
      <KeyValue
        k="Changes recorded"
        v={changes ? changes.total : "Not known"}
      />
    </div>
  );
}
