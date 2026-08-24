import { useEffect, useState } from "react";
import type { BumpBotStatus, GuildBumpStats } from "../api/types";
import { KeyValue, Rule, Stat } from "../_engine/components/overview/Tile";
import { formatDate } from "../_engine/format";
// Same two helpers this file has always used; they moved to the shared
// overview formatter so the home-page tiles report timings identically.
import { formatDuration, formatRelative } from "./overview/format";

/*
 * Per-bot bump status. Rendered INSIDE a Tile by whoever uses it, so it never
 * draws a card of its own.
 *
 * What it replaced: a grid of bespoke .bump-card boxes with their own type
 * scale, badge colours and countdown treatment - a second visual language on a
 * page that already had one. Every fact it showed is still here, on the shared
 * Stat / KeyValue / chip vocabulary, plus the two the old card left out:
 * whether a reminder actually went out for the newest bump, and how long this
 * server has been watched.
 *
 * The countdown still ticks once a second against the SERVER's clock, not the
 * browser's: the offset is measured once on mount so a skewed local clock can
 * never make a bump look ready before it is.
 */

function BotPanel({ bot, now }: { bot: BumpBotStatus; now: number }) {
  const ready = bot.status === "ready" || bot.next_due === null || now >= (bot.next_due ?? 0);
  const remaining = bot.next_due ? bot.next_due - now : 0;

  // `reminded_for` is the bump timestamp the last delivered reminder covered.
  // It is only present on the overview payload, so its absence means "not
  // reported here", never "no reminder was sent".
  const remindedKnown = bot.reminded_for !== undefined;
  const remindedFor = bot.reminded_for ?? null;
  const remindedForThis =
    bot.last_bump !== null && remindedFor !== null && remindedFor >= bot.last_bump;

  return (
    <div className="ov-card ov-card--quiet" style={{ gap: 8 }}>
      <div className="ov-card__head">
        <span className="ov-card__title">{bot.name}</span>
        {ready ? (
          <span className="ov-chip ov-chip--good">Ready now</span>
        ) : (
          <span className="ov-chip ov-chip--live">Cooling down</span>
        )}
      </div>

      <Stat
        small
        value={ready ? "Bump it" : formatDuration(remaining)}
        label={ready ? "Ready to bump" : "Until the next bump"}
      />

      <div>
        <KeyValue
          k="Last bumped"
          v={bot.last_bump ? formatRelative(bot.last_bump, now) : "Never seen"}
        />
        <KeyValue k="Cooldown" v={formatDuration(bot.cooldown)} />
        {remindedKnown && (
          <KeyValue
            k="Reminder sent for this bump"
            v={
              bot.last_bump === null
                ? "Nothing to remind about yet"
                : remindedForThis
                  ? "Yes"
                  : "Not yet"
            }
          />
        )}
      </div>
    </div>
  );
}

interface BumpStatusGridProps {
  stats: GuildBumpStats;
  /** When this server's settings were first written, so the page can say how
   *  long it has been watched. Absent when the caller does not have it. */
  createdAt?: string | null;
}

export default function BumpStatusGrid({ stats, createdAt }: BumpStatusGridProps) {
  // Offset (seconds) between this browser's clock and the server's, computed once.
  const [offset] = useState(() => Date.now() / 1000 - stats.server_time);
  const [now, setNow] = useState(() => Date.now() / 1000 - offset);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000 - offset), 1000);
    return () => clearInterval(id);
  }, [offset]);

  return (
    <>
      <div className="ov-statrow">
        <Stat small value={stats.enabled_count} label="Bump bots tracked" />
        <div>
          <div className="ov-card__head" style={{ minHeight: 34 }}>
            {stats.config_complete ? (
              <span className="ov-chip ov-chip--good">Setup complete</span>
            ) : (
              <span className="ov-chip ov-chip--warn">Setup incomplete</span>
            )}
          </div>
          <div className="ov-stat-l">This server</div>
        </div>
      </div>

      <Rule />

      {stats.bots.length === 0 ? (
        <p className="ov-body">
          No bump bots are being tracked in this server yet, so there is nothing to time. Pick
          the listing services this server bumps on and their countdowns appear here.
        </p>
      ) : (
        <div className="ov-cols ov-cols--3 bump-cols">
          {stats.bots.map((bot) => (
            <BotPanel key={bot.key} bot={bot} now={now} />
          ))}
        </div>
      )}

      {createdAt && (
        <p className="ov-muted">Watching this server since {formatDate(createdAt)}.</p>
      )}
    </>
  );
}
