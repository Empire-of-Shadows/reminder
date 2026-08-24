import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchPublicStats, type PublicStats } from "../api/client";

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}

export default function LoginPage() {
  const [stats, setStats] = useState<PublicStats | null>(null);

  useEffect(() => {
    let alive = true;
    fetchPublicStats().then((s) => {
      if (alive) setStats(s);
    });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <main className="login-main">
      <div className="login-hero">
        <img className="login-mark" src="/brand/artifact-belltower.svg" alt="" />
        <h1>Imperial Reminder</h1>
        <p className="tagline">
          Sign in with Discord to manage your server's bump reminders. Your Empire of Shadows
          session is shared - one login covers every bot dashboard.
        </p>
        <a href="/auth/discord" className="cta">
          Login with Discord
        </a>
        <p className="muted" style={{ marginTop: "0.75rem", fontSize: "0.85rem" }}>
          One login covers every Empire of Shadows dashboard, so by signing in you agree to the{" "}
          <a
            href="https://eosofficial.club/privacy"
            target="_blank"
            rel="noopener noreferrer"
          >
            Empire of Shadows Privacy Policy
          </a>
          , which covers every bot, dashboard, and tool in the ecosystem. Imperial Reminder has its
          own <Link to="/privacy">privacy page</Link> for the detail specific to this bot.
        </p>
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          New here?{" "}
          <a
            href="https://eosofficial.club/about"
            target="_blank"
            rel="noopener noreferrer"
          >
            Read what this project is about
          </a>{" "}
          - six bots, one ecosystem, and why it is built that way.
        </p>

        <div className="login-divider">Explore the ecosystem</div>

        <div className="login-tiles">
          <a className="tile-button" href="https://eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">Main Site</span>
            <span className="tile-desc">Empire of Shadows hub - news, links, community.</span>
          </a>
          <a className="tile-button" href="https://host.eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">TheHost</span>
            <span className="tile-desc">Games and stats dashboard for TheHost bot.</span>
          </a>
          <a className="tile-button" href="https://codex.eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">TheCodex</span>
            <span className="tile-desc">Guides, polls, and stats for TheCodex bot.</span>
          </a>
          <a className="tile-button" href="https://ecom.eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">Ecom</span>
            <span className="tile-desc">Leveling, embers, and economy for the Ecom bot.</span>
          </a>
        </div>

        {stats && (
          <>
            <div className="login-stats">
              <span>
                <span className="stat-num">{formatCount(stats.servers)}</span>servers
              </span>
              <span className="stat-sep">·</span>
              <span>
                <span className="stat-num">{formatCount(stats.bots_tracked)}</span>bots tracked
              </span>
              {/* Only shown when the counter is actually in the payload - an older
                  cached response has no field for it, and 0 would read as
                  "nobody has finished setting up", which is a different claim. */}
              {stats.servers_ready !== undefined && (
                <>
                  <span className="stat-sep">·</span>
                  <span>
                    <span className="stat-num">{formatCount(stats.servers_ready)}</span>fully set
                    up
                  </span>
                </>
              )}
            </div>

            {stats.per_bot && stats.per_bot.some((bot) => bot.servers > 0) && (
              <p className="login-services">
                Being watched right now:{" "}
                {stats.per_bot
                  .filter((bot) => bot.servers > 0)
                  .map(
                    (bot) =>
                      `${bot.name} in ${formatCount(bot.servers)} ${
                        bot.servers === 1 ? "server" : "servers"
                      }`,
                  )
                  .join(", ")}
                .
              </p>
            )}
          </>
        )}
      </div>
      <div className="login-below" />
    </main>
  );
}
