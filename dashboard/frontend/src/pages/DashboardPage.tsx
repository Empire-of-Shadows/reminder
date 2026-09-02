import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, fetchPublicStats, type PublicStats } from "../api/client";
import type { Guild, User } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { formatCount } from "../_engine/format";
import ServerPicker, { pickerMeta } from "../_engine/components/overview/ServerPicker";
import { Tile } from "../_engine/components/overview/Tile";
import AppHeader from "../components/AppHeader";
import PageSkeleton from "../components/PageSkeleton";

/*
 * The dashboard home.
 *
 * Two things, and only these two: how much work the bot is doing across the
 * whole Empire, and the picker that takes you to one of your own servers.
 *
 * A single server's view is NOT here. It lives at
 * `/me/guilds/:id/overview`, and picking a server here navigates there. This
 * page used to render the picked server inline off a `?guild=` parameter, which
 * left one per-server view addressed by a query string while every other page
 * used a path, and hid that server's tab bar until you had already left the page
 * it was on. The old `/me?guild=` and `/dashboard?guild=` links are still out
 * there in Discord messages and bookmarks, so both are redirected to the
 * server's overview rather than dropped (see App).
 *
 * Imperial Reminder has nothing per-member to total up across servers - it
 * tracks servers, not people - so there is deliberately no combined activity
 * section under the picker. The Empire-wide counts in the hero are the honest
 * cross-server thing this bot can say.
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

export default function DashboardPage() {
  const navigate = useNavigate();

  const [user, setUser] = useState<User | null>(null);
  const [guilds, setGuilds] = useState<Guild[]>([]);
  const [stats, setStats] = useState<PublicStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [u, g] = await Promise.all([api.me(), api.guilds()]);
        if (!alive) return;
        setUser(u);
        setGuilds(g);
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
  }, []);

  // Picking a server is navigation now, not selection: this page holds no
  // per-server state to set. "All servers" is what this page already is, so
  // choosing it stays put rather than routing anywhere.
  function selectGuild(id: string | null) {
    if (id) navigate(`/me/guilds/${id}/overview`);
  }

  if (loading) return <PageSkeleton />;

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
              // Nothing is ever selected here: this page IS the list of your
              // servers, and choosing one leaves it for that server's overview.
              selectedGuildId={null}
              onSelect={selectGuild}
              meta={pickerMeta(null, guilds.length, "Imperial Reminder")}
            />
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
        ) : (
          <QuietGrid>
            <Tile span={12} quiet title="Pick a server">
              <p className="ov-body">
                Choose a server above to see its bump timers and whether the reminder reaches
                you.
              </p>
            </Tile>
          </QuietGrid>
        )}
      </div>
    </div>
  );
}

/** One tile on its own row, for the states that are not a full composition. */
function QuietGrid({ children }: { children: ReactNode }) {
  return <div className="ov-grid">{children}</div>;
}
