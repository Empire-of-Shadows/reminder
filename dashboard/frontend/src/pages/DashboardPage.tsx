import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api, fetchPublicStats, inviteLink, type PublicStats } from "../api/client";
import type {
  Guild,
  GuildBumpStats,
  GuildOverview,
  MemberReminder,
  User,
} from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { formatCount } from "../_engine/format";
import ServerPicker, { pickerMeta } from "../_engine/components/overview/ServerPicker";
import SignalStrip, { type Signal } from "../_engine/components/overview/SignalStrip";
import { Tile } from "../_engine/components/overview/Tile";
import AppHeader from "../components/AppHeader";
import PageSkeleton from "../components/PageSkeleton";
import AdminOverview from "../components/overview/AdminOverview";
import MemberOverview from "../components/overview/MemberOverview";
import { formatCountdown, formatRelative } from "../components/overview/format";

/*
 * The dashboard home.
 *
 * What this replaced: a horizontally-scrolling pill bar of servers over one
 * grid of bump cards, with no width cap - on a wide monitor the cards held a
 * countdown in a box the width of the screen, and nothing on the page answered
 * "is any of this actually working". The layout is now the shared engine one:
 * a command row (which server, and the numbers that are only numbers) above a
 * 12-column grid of tiles.
 *
 * Composition order is member first, then server. Somebody with Manage Server
 * is a member of that server before they are its administrator, and "does this
 * thing ping ME" is the question they arrived with. The server sections follow
 * underneath for the people who can act on them.
 *
 * Every member request is additive and independently failure-tolerant: the
 * roles lookup behind "will you be pinged" talks to Discord and can fail on its
 * own without costing the page the timings, the server overview, or each other.
 */

function StatsHero({ stats }: { stats: PublicStats | null }) {
  return (
    <section className="dash-hero">
      <div className="dash-hero__orb" />
      <img className="dash-hero__sigil" src="/brand/artifact-belltower.svg" alt="" />
      <div className="dash-hero__copy">
        <span className="dash-hero__eyebrow">Empire Overview</span>
        <h1 className="dash-hero__title">Imperial Reminder</h1>
        <p className="dash-hero__sub">
          {stats ? (
            <>
              Keeping <strong>{formatCount(stats.bots_tracked)}</strong> bump bots on schedule
              across {formatCount(stats.servers)} servers.
            </>
          ) : (
            <>Never miss a bump again.</>
          )}
        </p>
      </div>
      {stats && (
        <div className="dash-hero__strip">
          <div className="empire-stat">
            <div className="empire-stat__value">{formatCount(stats.servers)}</div>
            <div className="empire-stat__label">Servers</div>
          </div>
          <div className="empire-stat">
            <div className="empire-stat__value">{formatCount(stats.bots_tracked)}</div>
            <div className="empire-stat__label">Bots Tracked</div>
          </div>
        </div>
      )}
    </section>
  );
}

/** What loaded for the member half of the selected server. */
interface MemberPane {
  bumps: GuildBumpStats | null;
  reminder: MemberReminder | null;
}

const EMPTY_MEMBER: MemberPane = { bumps: null, reminder: null };

export default function DashboardPage() {
  const [user, setUser] = useState<User | null>(null);
  const [guilds, setGuilds] = useState<Guild[]>([]);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [stats, setStats] = useState<PublicStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchParams, setSearchParams] = useSearchParams();
  const selectedGuildId = searchParams.get("guild");
  const [overview, setOverview] = useState<GuildOverview | null>(null);
  const [member, setMember] = useState<MemberPane>(EMPTY_MEMBER);
  const [paneLoading, setPaneLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  // The ?guild= value the page was opened with. A shared link always wins over
  // the default-to-your-own-server behaviour below.
  const openedWith = useRef<string | null>(searchParams.get("guild"));

  function selectGuild(id: string | null) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("guild", id);
        else next.delete("guild");
        return next;
      },
      { replace: true },
    );
  }

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [u, g, invite] = await Promise.all([
          api.me(),
          api.guilds(),
          api.botInviteUrl().catch(() => ({ url: null })),
        ]);
        if (!alive) return;
        setUser(u);
        setGuilds(g);
        setInviteUrl(invite.url);
        if (!openedWith.current) {
          // Land on a server the bot is actually in, so the page has something
          // to say on arrival - one this person manages if there is one, and
          // otherwise any server they share with the bot, which is all a plain
          // member has. Written with replace, so the URL stays shareable.
          const usable = g.filter((entry) => entry.bot_in_guild && !entry.setup_required);
          const own = usable.find((entry) => entry.panel_role === "admin") ?? usable[0];
          if (own) selectGuild(own.id);
        }
      } catch (e) {
        if (alive) setError(formatError(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    fetchPublicStats().then((s) => {
      if (alive) setStats(s);
    });
    return () => {
      alive = false;
    };
    // Runs once: the initial guild comes from the URL, captured above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedGuild = useMemo(
    () => (selectedGuildId ? guilds.find((g) => g.id === selectedGuildId) ?? null : null),
    [guilds, selectedGuildId],
  );

  const botPresent =
    selectedGuild !== null && selectedGuild.bot_in_guild && !selectedGuild.setup_required;
  const isAdmin = botPresent && selectedGuild?.panel_role === "admin";

  // Fetch the selected server's panes whenever the selection changes.
  useEffect(() => {
    if (!selectedGuildId || !botPresent) {
      setOverview(null);
      setMember(EMPTY_MEMBER);
      setOverviewError(null);
      return;
    }
    let alive = true;
    setPaneLoading(true);
    setOverviewError(null);

    // Every member request swallows its own failure and resolves to null, so
    // one of them being down can never blank the others or the server sections.
    const swallow = <T,>(p: Promise<T>): Promise<T | null> =>
      p.then(
        (value) => value,
        (e) => {
          console.error("Member section fetch failed", e);
          return null;
        },
      );

    const memberRequest = Promise.all([
      swallow(api.memberBumps(selectedGuildId)),
      swallow(api.memberReminder(selectedGuildId)),
    ]).then(([bumps, reminder]) => ({ bumps, reminder }));

    const overviewRequest: Promise<GuildOverview | null | "error"> = isAdmin
      ? api.guildOverview(selectedGuildId).catch((e) => {
          if ((e as Error).message === "Unauthorized") return null;
          console.error("Server overview fetch failed", e);
          return "error" as const;
        })
      : Promise.resolve(null);

    Promise.all([memberRequest, overviewRequest])
      .then(([memberPane, serverOverview]) => {
        if (!alive) return;
        setMember(memberPane);
        if (serverOverview === "error") {
          setOverview(null);
          setOverviewError("This server's overview could not be loaded.");
        } else {
          setOverview(serverOverview);
        }
      })
      .finally(() => {
        if (alive) setPaneLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [selectedGuildId, botPresent, isAdmin]);

  if (loading) return <PageSkeleton />;

  const anyMemberSection =
    member.bumps !== null || member.reminder !== null;

  return (
    <div className="app-layout">
      <AppHeader user={user} />

      <div className="page">
        <StatsHero stats={stats} />

        {error && (
          <div className="alert danger" role="alert" style={{ marginTop: 16 }}>
            {error}
          </div>
        )}

        {guilds.length > 0 && (
          <div className="ov-command">
            <ServerPicker
              guilds={guilds}
              selectedGuildId={selectedGuildId}
              onSelect={selectGuild}
              meta={pickerMeta(selectedGuild, guilds.length, "Imperial Reminder")}
            />
            <SignalStrip signals={signalsFor(overview, member.bumps)} />
          </div>
        )}

        {guilds.length === 0 ? (
          <QuietGrid>
            <Tile span={12} quiet title="No servers">
              <p className="ov-body">
                {error
                  ? "Your servers could not be loaded just now, so this list is not empty - it is unknown. Reload the page to try again."
                  : "You do not share a server with Imperial Reminder yet. Servers appear here once the bot is in one you are a member of."}
              </p>
            </Tile>
          </QuietGrid>
        ) : !selectedGuild ? (
          <QuietGrid>
            <Tile span={12} quiet title="Pick a server">
              <p className="ov-body">
                Choose a server above to see its bump timers and whether the reminder reaches
                you.
              </p>
            </Tile>
          </QuietGrid>
        ) : selectedGuild.setup_required ? (
          <QuietGrid>
            <Tile
              span={12}
              quiet
              title="Not added yet"
              chips={<span className="ov-chip ov-chip--warn">Bot missing</span>}
            >
              <p className="ov-body">
                Imperial Reminder is not in <strong>{selectedGuild.name}</strong> yet. Add it,
                then come back here to set the bump channel and reminder role.
              </p>
              {inviteUrl && (
                <div className="admin-actions">
                  <a
                    className="btn btn-primary"
                    href={inviteLink(inviteUrl, selectedGuild.id)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Invite the bot
                  </a>
                </div>
              )}
            </Tile>
          </QuietGrid>
        ) : paneLoading ? (
          <div className="ov-grid" role="status" aria-busy="true">
            <div className="skeleton-card s7" />
            <div className="skeleton-card s5" />
            <div className="skeleton-card s12" />
            <div className="skeleton-card s4" />
            <div className="skeleton-card s3" />
            <div className="skeleton-card s5" />
            <span className="visually-hidden">Loading this server</span>
          </div>
        ) : (
          <>
            <h2 className="section-title" style={{ margin: "4px 0 12px" }}>
              Your reminders
            </h2>
            <MemberOverview
              bumps={member.bumps}
              reminder={member.reminder}
              detailed={!isAdmin}
            />

            {isAdmin && (
              <>
                <h2 className="section-title" style={{ margin: "28px 0 12px" }}>
                  Server overview
                </h2>
                {overview ? (
                  <AdminOverview overview={overview} />
                ) : (
                  <QuietGrid>
                    <Tile span={12} quiet title="Not loaded">
                      <p className="ov-body" role="alert">
                        {overviewError ??
                          "This server's overview could not be loaded. Refresh to try again."}
                      </p>
                    </Tile>
                  </QuietGrid>
                )}
              </>
            )}


            {!anyMemberSection && !isAdmin && (
              <p className="ov-muted" style={{ marginTop: 16 }}>
                Nothing about this server could be loaded just now. That is a fault on our
                side, not an empty server - reload the page to try again.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** One tile on its own row, for the states that are not a full composition. */
function QuietGrid({ children }: { children: ReactNode }) {
  return <div className="ov-grid">{children}</div>;
}

/* ── The command-row numbers ───────────────────────────────────────── */

function signalsFor(
  overview: GuildOverview | null,
  memberBumps: GuildBumpStats | null,
): Signal[] {
  const bumps = overview?.bumps ?? null;

  // An admin reads the server's roll-up; a member reads the same timings
  // computed from the rows they are allowed to see. Neither is invented.
  if (bumps) {
    const signals: Signal[] = [
      { key: "tracked", value: formatCount(bumps.enabled_count), label: "Bots tracked" },
      { key: "ready", value: formatCount(bumps.ready_count), label: "Ready to bump" },
      {
        key: "next",
        value:
          bumps.next_due !== null
            ? formatCountdown(bumps.next_due, bumps.now).replace(/^in /, "")
            : "-",
        label: bumps.next_due !== null ? "Until next bump" : "Next bump - none due",
      },
      {
        key: "last",
        value: bumps.last_bump !== null ? formatRelative(bumps.last_bump, bumps.now) : "-",
        label: bumps.last_bump !== null ? "Last bump" : "Last bump - none seen",
      },
    ];
    return signals;
  }

  if (!memberBumps) return [];

  const now = memberBumps.server_time;
  let ready = 0;
  let nextDue: number | null = null;
  let lastBump: number | null = null;
  for (const bot of memberBumps.bots) {
    if (bot.status === "ready") ready += 1;
    else if (bot.next_due !== null) {
      nextDue = nextDue === null ? bot.next_due : Math.min(nextDue, bot.next_due);
    }
    if (bot.last_bump !== null) {
      lastBump = lastBump === null ? bot.last_bump : Math.max(lastBump, bot.last_bump);
    }
  }

  return [
    { key: "tracked", value: formatCount(memberBumps.enabled_count), label: "Bots tracked" },
    { key: "ready", value: formatCount(ready), label: "Ready to bump" },
    {
      key: "next",
      value: nextDue !== null ? formatCountdown(nextDue, now).replace(/^in /, "") : "-",
      label: nextDue !== null ? "Until next bump" : "Next bump - none due",
    },
    {
      key: "last",
      value: lastBump !== null ? formatRelative(lastBump, now) : "-",
      label: lastBump !== null ? "Last bump" : "Last bump - none seen",
    },
  ];
}
