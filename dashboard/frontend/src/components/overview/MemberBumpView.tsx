import { useEffect, useState } from "react";
import type { MyBumpTimer, MyBumpView } from "../../api/types";
import { KeyValue, Rule, Stat, Tile } from "../../_engine/components/overview/Tile";
import { formatCountdown } from "./format";

/*
 * The server page as a plain member sees it.
 *
 * Imperial Reminder's dashboard is an admin tool - every control on it changes
 * how the bot behaves for the whole server, and a member has none of them. So
 * this pane answers exactly one question and refuses to pad: does the reader
 * hold this server's bump role?
 *
 *   yes  -> the countdowns, which is the one thing on this dashboard a bumper
 *           actually uses.
 *   no   -> said plainly: this is where admins set the bot up, and there is
 *           nothing here for you. Better than a page of tiles reporting a
 *           server's state to somebody who cannot act on any of it.
 *   null -> we could not check. This case exists so the "nothing here for you"
 *           sentence is never printed off a failed read; being told the site
 *           has nothing for you when it does is worse than being asked to
 *           reload.
 *
 * Nothing here is invented on top of that ruling. There is no "ask an admin"
 * button, no self-service role request, no notification opt-in - the bot has
 * none of those, and a dashboard that offers them would be lying.
 */

export default function MemberBumpView({ view }: { view: MyBumpView | null }) {
  // The request failed outright. Same reasoning as the null role check: a
  // fault on our side must never render as a verdict about the reader.
  if (!view) {
    return (
      <div className="ov-grid">
        <Tile span={12} quiet title="Not loaded">
          <p className="ov-body" role="alert">
            This server's page could not be loaded just now. That is a fault on our side,
            not an empty server - reload the page to try again.
          </p>
        </Tile>
      </div>
    );
  }

  if (view.holds_bump_role === null) {
    return (
      <div className="ov-grid">
        <Tile
          span={12}
          quiet
          title="Could not check"
          chips={<span className="ov-chip ov-chip--warn">Unconfirmed</span>}
        >
          <p className="ov-body">
            We could not check your roles in this server just now, so we will not guess at
            what belongs on your page. Reload to try again.
          </p>
        </Tile>
      </div>
    );
  }

  if (view.holds_bump_role === false) {
    return <NothingHereForYou configured={view.configured} />;
  }

  return <BumpTimers timers={view.timers} serverTime={view.server_time} />;
}

/* ── Holds the role: the countdowns ────────────────────────────────────── */

function BumpTimers({
  timers,
  serverTime,
}: {
  timers: MyBumpTimer[] | null;
  serverTime: number;
}) {
  // Countdowns tick against the SERVER's clock, not the browser's: the offset
  // is measured once on mount, exactly as BumpStatusGrid does it, so a skewed
  // local clock can never show a bump as ready before it is.
  const [offset] = useState(() => Date.now() / 1000 - serverTime);
  const [now, setNow] = useState(() => Date.now() / 1000 - offset);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000 - offset), 1000);
    return () => clearInterval(id);
  }, [offset]);

  if (timers === null) {
    return (
      <div className="ov-grid">
        <Tile span={12} quiet title="Bump timers">
          <p className="ov-body" role="alert">
            This server's bump timings could not be worked out just now. Reload the page to
            try again - and the countdowns are always posted in the server's bump channel.
          </p>
        </Tile>
      </div>
    );
  }

  if (timers.length === 0) {
    return (
      <div className="ov-grid">
        <Tile span={12} quiet title="Bump timers">
          <p className="ov-body">
            Nobody has chosen which listing services this server bumps on yet, so there is
            nothing being timed. A server admin picks them in the bot's settings.
          </p>
        </Tile>
      </div>
    );
  }

  const readyCount = timers.filter((timer) => timer.ready_now).length;
  // The soonest cooldown still running, which is what "when can I bump next"
  // actually means. Bots already ready are excluded - they have no future time.
  let nextDue: number | null = null;
  for (const timer of timers) {
    if (timer.ready_now || timer.ready_at === null) continue;
    nextDue = nextDue === null ? timer.ready_at : Math.min(nextDue, timer.ready_at);
  }

  return (
    <div className="ov-grid">
      <Tile
        span={12}
        title="Bump timers"
        live
        chips={
          readyCount > 0 ? (
            <span className="ov-chip ov-chip--good">{readyCount} ready to bump now</span>
          ) : (
            <span className="ov-chip">Everything is on cooldown</span>
          )
        }
      >
        <p className="ov-body">
          You hold this server's bump reminder role, so the bot mentions you when a bump
          comes off cooldown. Here is where each listing service stands.
        </p>

        <div className="ov-statrow">
          <Stat
            value={nextDue !== null ? formatCountdown(nextDue, now).replace(/^in /, "") : "-"}
            label={nextDue !== null ? "Until the next bump" : "Nothing waiting"}
          />
          <Stat small value={readyCount} sub={`/${timers.length}`} label="Ready now" />
        </div>

        <Rule />

        <div>
          {timers.map((timer) => (
            <KeyValue
              key={timer.bot}
              k={timer.bot}
              v={
                timer.ready_now ? (
                  <span className="ov-chip ov-chip--good">Ready now</span>
                ) : timer.ready_at !== null ? (
                  `Ready ${formatCountdown(timer.ready_at, now)}`
                ) : (
                  // Belt and braces: the API only omits a time for a bot that
                  // is ready, but a member must never be shown a blank row.
                  "Still on cooldown"
                )
              }
            />
          ))}
        </div>
      </Tile>
    </div>
  );
}

/* ── Does not hold the role: the honest note ───────────────────────────── */

function NothingHereForYou({ configured }: { configured: boolean }) {
  return (
    <div className="ov-grid">
      <Tile span={12} quiet title="This dashboard is for server admins">
        <p className="ov-body">
          This is where a server's admins set Imperial Reminder up: the channel it watches,
          the role it pings, and which listing services it counts down. There is nothing
          here for you to change, and nothing you are missing by not opening it.
        </p>
        <p className="ov-body">
          {configured
            ? "If you help bump this server, the countdowns are posted in the server's own bump channel - that is where to watch them."
            : "This server has not finished setting the bot up yet, so nothing is being counted down anywhere. A server admin does that from here."}
        </p>
      </Tile>
    </div>
  );
}
