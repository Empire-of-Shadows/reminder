import { Link } from "react-router-dom";
import type {
  BumpsOverview,
  ChangesOverview,
  GuildOverview,
  SetupOverview,
} from "../../api/types";
import BarChart, { type BarChartSeries } from "../../_engine/components/charts/BarChart";
import FeatureStrip, { featureCounts } from "../../_engine/components/overview/FeatureStrip";
import {
  KeyValue,
  Rule,
  SectionUnavailable,
  Stat,
  Tile,
} from "../../_engine/components/overview/Tile";
import { formatCount, formatDayLabel, formatRelative as formatIsoRelative } from "../../_engine/format";
import BumpStatusGrid from "../BumpStatusGrid";
import { changeLabel, formatCountdown } from "./format";

/** Where one setting is edited. This bot's settings page lives under
 *  `/settings/guilds/<id>/settings`, not at the engine's older flat default, so
 *  the links here and the builder handed to FeatureStrip both come from one
 *  place rather than being spelled out five times. */
function settingsHref(guildId: string, section?: string): string {
  const base = `/settings/guilds/${guildId}/settings`;
  return section ? `${base}?s=${encodeURIComponent(section)}` : base;
}

/** The server home. Every section of the payload can be null on its own. */
export default function AdminOverview({ overview }: { overview: GuildOverview }) {
  const guildId = overview.guild_id;
  return (
    <div className="ov-grid">
      <IsItWorking overview={overview} />
      <BumpTimers guildId={guildId} bumps={overview.bumps} setup={overview.setup} />
      <SetupHealth guildId={guildId} setup={overview.setup} />
      <ChangeActivity guildId={guildId} changes={overview.changes} />
    </div>
  );
}

/* ── Is it working ─────────────────────────────────────────────────── */

function IsItWorking({ overview }: { overview: GuildOverview }) {
  const guildId = overview.guild_id;
  const counts = featureCounts(overview.features);
  return (
    <Tile
      span={12}
      title="Is it working"
      chips={
        <>
          {counts.on > 0 && <span className="ov-chip ov-chip--good">{counts.on} running</span>}
          {counts.needsSetup > 0 && (
            <span className="ov-chip ov-chip--warn">{counts.needsSetup} need setting up</span>
          )}
          {counts.off > 0 && <span className="ov-chip">{counts.off} off</span>}
        </>
      }
      action={
        <Link className="ov-link" to={settingsHref(guildId)}>
          Change settings
        </Link>
      }
    >
      <FeatureStrip
        guildId={guildId}
        features={overview.features}
        settingsHref={(key) => settingsHref(guildId, key)}
      />
    </Tile>
  );
}

/* ── Bump timers ───────────────────────────────────────────────────── */

function BumpTimers({
  guildId,
  bumps,
  setup,
}: {
  guildId: string;
  bumps: BumpsOverview | null;
  setup: SetupOverview | null;
}) {
  if (!bumps) {
    return (
      <Tile span={12} title="Bump timers">
        <SectionUnavailable what="Bump timers" />
      </Tile>
    );
  }

  if (bumps.bots.length === 0) {
    return (
      <Tile
        span={12}
        title="Bump timers"
        chips={<span className="ov-chip ov-chip--warn">No bots selected</span>}
        action={
          <Link className="ov-link" to={settingsHref(guildId, "bots")}>
            Choose bump bots
          </Link>
        }
      >
        <p className="ov-body">
          No bump bots are being tracked in this server yet, so nothing is being timed. Pick the
          listing services you bump on and their timers appear here.
        </p>
      </Tile>
    );
  }

  const next =
    bumps.next_due !== null ? formatCountdown(bumps.next_due, bumps.now) : null;

  return (
    <Tile
      span={12}
      title="Bump timers"
      live
      chips={
        <>
          {bumps.ready_count > 0 ? (
            <span className="ov-chip ov-chip--good">{bumps.ready_count} ready now</span>
          ) : (
            <span className="ov-chip">All on cooldown</span>
          )}
          {bumps.reminders_pending > 0 && (
            <span className="ov-chip ov-chip--warn">
              {bumps.reminders_pending} not reminded yet
            </span>
          )}
          {next && <span className="ov-chip ov-chip--live">Next {next}</span>}
        </>
      }
      action={
        <Link className="ov-link" to={settingsHref(guildId, "bots")}>
          Bump bots
        </Link>
      }
    >
      <BumpStatusGrid stats={bumps} createdAt={setup?.created_at ?? null} />
      {bumps.never_bumped > 0 && (
        <p className="ov-muted">
          {bumps.never_bumped} of them {bumps.never_bumped === 1 ? "has" : "have"} never been seen
          bumping in this server. That is normal until the first bump goes through the channel the
          bot is watching.
        </p>
      )}
    </Tile>
  );
}

/* ── Setup health ──────────────────────────────────────────────────── */

function setLabel(value: string): string {
  return value ? "Set" : "Not set";
}

function SetupHealth({ guildId, setup }: { guildId: string; setup: SetupOverview | null }) {
  if (!setup) {
    return (
      <Tile span={4} title="Setup">
        <SectionUnavailable what="This server's setup" />
      </Tile>
    );
  }

  const missing =
    (setup.bump_channel ? 0 : 1) +
    (setup.bump_role ? 0 : 1) +
    (setup.enabled_bots.length ? 0 : 1);

  return (
    <Tile
      span={4}
      title="Setup"
      chips={
        missing === 0 ? (
          <span className="ov-chip ov-chip--good">Ready</span>
        ) : (
          <span className="ov-chip ov-chip--warn">
            {missing} thing{missing === 1 ? "" : "s"} missing
          </span>
        )
      }
      action={
        <Link className="ov-link" to={settingsHref(guildId, "bumps")}>
          Edit
        </Link>
      }
    >
      <div className="ov-statrow">
        <Stat
          small
          value={formatCount(setup.enabled_bots.length)}
          sub={`/${setup.supported_bots.length}`}
          label="Bots tracked"
        />
        <Stat small value={formatCount(setup.admin_role_count)} label="Manager roles" />
      </div>
      <Rule />
      <div>
        <KeyValue k="Bump channel" v={setLabel(setup.bump_channel)} />
        <KeyValue k="Reminder role" v={setLabel(setup.bump_role)} />
        <KeyValue k="Timers channel" v={setLabel(setup.timers_channel)} />
        <KeyValue k="Live countdown" v={setup.timers_message ? "On" : "Off"} />
      </div>
      <p className="ov-muted">
        {setup.updated_at
          ? `Settings last saved ${formatIsoRelative(setup.updated_at)}.`
          : "These settings have not been saved from the dashboard or panel yet."}
      </p>
    </Tile>
  );
}


/* ── Change activity ───────────────────────────────────────────────── */

function ChangeActivity({ guildId, changes }: { guildId: string; changes: ChangesOverview | null }) {
  if (!changes) {
    return (
      <Tile span={5} title="Recent changes">
        <SectionUnavailable what="The change history" />
      </Tile>
    );
  }

  const groups = changes.daily.map((point) => formatDayLabel(point.date));
  const series: BarChartSeries[] = [
    { key: "changes", label: "Changes", values: changes.daily.map((point) => point.changes) },
  ];

  return (
    <Tile
      span={5}
      title="Recent changes"
      chips={
        changes.total_30d > 0 ? (
          <span className="ov-chip">{changes.total_30d} in 30 days</span>
        ) : null
      }
      action={
        <Link className="ov-link" to={settingsHref(guildId, "access")}>
          Who can manage
        </Link>
      }
    >
      <BarChart
        groups={groups}
        series={series}
        ariaLabel="Settings changed on each of the last 30 days"
        unit="changes"
        emptyLabel="Nothing has been changed in the last 30 days."
      />
      {changes.recent.length === 0 ? (
        <p className="ov-muted">
          Nothing has been changed yet. Every edit from the panel or this dashboard is recorded
          here for a year.
        </p>
      ) : (
        <div className="ov-queue">
          {changes.recent.map((entry, index) => (
            <div className="ov-qrow" key={`${entry.at ?? "unknown"}-${index}`}>
              <span className="ov-qrow__dot" style={{ background: "var(--text-accent)" }} />
              <span className="ov-qrow__txt">{changeLabel(entry)}</span>
              <span className="ov-qrow__meta">
                {entry.actor ? `${entry.actor} - ` : ""}
                {entry.at ? formatIsoRelative(entry.at) : "unknown"}
              </span>
            </div>
          ))}
        </div>
      )}
    </Tile>
  );
}
