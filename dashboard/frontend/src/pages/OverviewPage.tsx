import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, inviteLink } from "../api/client";
import type {
  Guild,
  GuildBumpStats,
  GuildOverview,
  MemberReminder,
  MyBumpView,
  User,
} from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { formatCount } from "../_engine/format";
import SignalStrip, { type Signal } from "../_engine/components/overview/SignalStrip";
import { Tile } from "../_engine/components/overview/Tile";
import AppHeader from "../components/AppHeader";
import GuildNav from "../components/GuildNav";
import PageSkeleton from "../components/PageSkeleton";
import AdminOverview from "../components/overview/AdminOverview";
import MemberBumpView from "../components/overview/MemberBumpView";
import MemberOverview from "../components/overview/MemberOverview";
import { formatCountdown, formatRelative } from "../components/overview/format";

/*
 * One server's page.
 *
 * This is where the dashboard home's `?guild=` view moved to. The home page used
 * to hold the picker AND everything about whichever server was picked, which
 * left one per-server view addressed by a query parameter while every other page
 * in the app used a path, and made the tab bar for a server invisible until you
 * had already left the page it lived on. Now `/me` is the picker and this is the
 * server, at an address that can be linked, bookmarked and shared.
 *
 * The page composes two different ways, because the two readers are asking
 * different questions.
 *
 * An ADMIN gets member-first, then server. Somebody with Manage Server is a
 * member of that server before they are its administrator, and "does this thing
 * ping ME" is the question they arrived with; the server sections follow
 * underneath for the people who can act on them. Every one of their member
 * requests is additive and independently failure-tolerant: the roles lookup
 * behind "will you be pinged" talks to Discord and can fail on its own without
 * costing the page the timings, the server overview, or each other.
 *
 * A plain MEMBER gets `MemberBumpView` and nothing else (owner ruling). This
 * dashboard is an admin tool - every control on it changes the bot for the whole
 * server - so reporting a server's state in detail to somebody who cannot act on
 * any of it was dressing an empty room. They now get the bump countdowns if they
 * are one of the people who bump, and otherwise a plain sentence saying this
 * place is for admins. That whole branch is one request, `myBumpView`, which
 * carries all three answers together.
 */

/** What loaded for the member half of an ADMIN's view of this server. */
interface MemberPane {
  bumps: GuildBumpStats | null;
  reminder: MemberReminder | null;
}

const EMPTY_MEMBER: MemberPane = { bumps: null, reminder: null };

export default function OverviewPage() {
  const { guildId = "" } = useParams();

  const [user, setUser] = useState<User | null>(null);
  const [guilds, setGuilds] = useState<Guild[]>([]);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [overview, setOverview] = useState<GuildOverview | null>(null);
  const [member, setMember] = useState<MemberPane>(EMPTY_MEMBER);
  // The plain-member branch. null after loading finishes means the one request
  // behind it failed, which MemberBumpView renders as "could not load" - never
  // as a verdict about the reader.
  const [myView, setMyView] = useState<MyBumpView | null>(null);
  const [paneLoading, setPaneLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);

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
      } catch (e) {
        if (alive) setError(formatError(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const guild = useMemo(
    () => guilds.find((g) => g.id === guildId) ?? null,
    [guilds, guildId],
  );

  const botPresent = guild !== null && guild.bot_in_guild && !guild.setup_required;
  const isAdmin = botPresent && guild?.panel_role === "admin";

  // Fetch this server's panes once the server list has told us what it is.
  useEffect(() => {
    if (!guildId || !botPresent) {
      setOverview(null);
      setMember(EMPTY_MEMBER);
      setMyView(null);
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

    // Only an admin's composition needs these two: their "Your reminders" pane
    // is the member tiles, and a failed overview falls back to the member
    // timings for the command row. A plain member's whole page is myBumpView,
    // so asking for these as well would be two unused Discord-backed calls.
    const memberRequest: Promise<MemberPane> = isAdmin
      ? Promise.all([
          swallow(api.memberBumps(guildId)),
          swallow(api.memberReminder(guildId)),
        ]).then(([bumps, reminder]) => ({ bumps, reminder }))
      : Promise.resolve(EMPTY_MEMBER);

    const myViewRequest: Promise<MyBumpView | null> = isAdmin
      ? Promise.resolve(null)
      : swallow(api.myBumpView(guildId));

    const overviewRequest: Promise<GuildOverview | null | "error"> = isAdmin
      ? api.guildOverview(guildId).catch((e) => {
          if ((e as Error).message === "Unauthorized") return null;
          console.error("Server overview fetch failed", e);
          return "error" as const;
        })
      : Promise.resolve(null);

    Promise.all([memberRequest, overviewRequest, myViewRequest])
      .then(([memberPane, serverOverview, memberView]) => {
        if (!alive) return;
        setMember(memberPane);
        setMyView(memberView);
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
  }, [guildId, botPresent, isAdmin]);

  if (loading) return <PageSkeleton />;

  // Computed up here so the padded command row is not drawn at all when there
  // is nothing to put in it: a plain member has no roll-up numbers (their whole
  // page is one pane), and an admin whose every source failed has none either.
  const signals = botPresent ? signalsFor(overview, member.bumps) : [];

  return (
    <div className="app-layout">
      <AppHeader user={user} />

      <div className="page">
        <GuildNav
          guildId={guildId}
          panelRole={guild?.panel_role}
          setupRequired={guild?.setup_required}
        />

        <section className="dash-hero">
          <div className="dash-hero__orb" />
          <img className="dash-hero__sigil" src="/brand/artifact-belltower.svg" alt="" />
          <div className="dash-hero__copy">
            <span className="dash-hero__eyebrow">Server</span>
            <h1 className="dash-hero__title">{guild?.name ?? "This server"}</h1>
            {/* A server the bot has not been added to has no reminder doing
                anything in it yet, so the standard line would be a claim the
                page then contradicts one card down. */}
            <p className="dash-hero__sub">
              {guild?.setup_required
                ? "Imperial Reminder has not been added to this server yet."
                : "What the bump reminder is doing here, and whether it reaches you."}
            </p>
          </div>
        </section>

        {error && (
          <div className="alert danger" role="alert" style={{ marginTop: 16 }}>
            {error}
          </div>
        )}

        {signals.length > 0 && (
          <div className="ov-command">
            <SignalStrip signals={signals} />
          </div>
        )}

        {!guild ? (
          <QuietGrid>
            <Tile span={12} quiet title="Server not found">
              <p className="ov-body">
                {error
                  ? "Your servers could not be loaded just now, so this one cannot be shown. Reload the page to try again."
                  : "This is not a server you share with Imperial Reminder, or it is no longer in your list."}
              </p>
              <div className="admin-actions">
                <Link className="btn btn-primary" to="/me">
                  Back to your servers
                </Link>
              </div>
            </Tile>
          </QuietGrid>
        ) : guild.setup_required ? (
          <QuietGrid>
            <Tile
              span={12}
              quiet
              title="Not added yet"
              chips={<span className="ov-chip ov-chip--warn">Bot missing</span>}
            >
              <p className="ov-body">
                Imperial Reminder is not in <strong>{guild.name}</strong> yet. Add it, then
                come back here to set the bump channel and reminder role.
              </p>
              {inviteUrl && (
                <div className="admin-actions">
                  <a
                    className="btn btn-primary"
                    href={inviteLink(inviteUrl, guild.id)}
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
          // The placeholder matches the composition that is coming: an admin
          // gets six cards, a member gets the one pane they will actually see.
          // A six-card skeleton in front of a single tile promises a page that
          // never arrives.
          <div className="ov-grid" role="status" aria-busy="true">
            {isAdmin ? (
              <>
                <div className="skeleton-card s7" />
                <div className="skeleton-card s5" />
                <div className="skeleton-card s12" />
                <div className="skeleton-card s4" />
                <div className="skeleton-card s3" />
                <div className="skeleton-card s5" />
              </>
            ) : (
              <div className="skeleton-card s12" />
            )}
            <span className="visually-hidden">Loading this server</span>
          </div>
        ) : isAdmin ? (
          <>
            <h2 className="section-title" style={{ margin: "4px 0 12px" }}>
              Your reminders
            </h2>
            {/* An admin's member pane stays the roll-up only - the per-bot grid
                is already in the Server overview below, and printing it twice
                is noise, not density. */}
            <MemberOverview
              bumps={member.bumps}
              reminder={member.reminder}
            />

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
        ) : (
          <MemberBumpView view={myView} />
        )}
      </div>
    </div>
  );
}

/** One tile on its own row, for the states that are not a full composition. */
function QuietGrid({ children }: { children: ReactNode }) {
  return <div className="ov-grid">{children}</div>;
}

/* The command-row numbers */

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
