import { Component, type ReactNode } from "react";
import type { BumpBot, Channel, GuildOverview, GuildSettings, Role } from "../../api/types";
import { changeLabel, formatCountdown, formatDuration, formatRelative } from "../overview/format";

/*
 * The right-hand column: what the selected setting is doing right now.
 *
 * Two sources feed it. The settings response is always there, so the "what is
 * configured" rows always render. The guild overview endpoint is optional - it
 * can fail or come back with null sections, and when it does those rows are
 * simply left out. Nothing here may throw when `overview` is null.
 */

function KvCard({
  title,
  rows,
  footer,
}: {
  title: string;
  rows: [string, string][];
  footer?: string;
}) {
  if (rows.length === 0 && !footer) return null;
  return (
    <div className="ov-card">
      <div className="ov-card__head">
        <span className="ov-card__title">{title}</span>
      </div>
      <div>
        {rows.map(([k, v]) => (
          <div className="ov-kv" key={k}>
            <span className="ov-kv__k">{k}</span>
            <span className="ov-kv__v">{v}</span>
          </div>
        ))}
      </div>
      {footer && <p className="ov-muted" style={{ margin: 0 }}>{footer}</p>}
    </div>
  );
}

function onOff(value: boolean): string {
  return value ? "On" : "Off";
}

function channelName(channels: Channel[], id: string): string {
  if (!id) return "Not set";
  const hit = channels.find((c) => c.id === id);
  return hit ? `#${hit.name}` : "Set (channel not visible)";
}

function roleName(roles: Role[], id: string): string {
  if (!id) return "Not set";
  const hit = roles.find((r) => r.id === id);
  return hit ? hit.name : "Set (role not visible)";
}

interface ContextProps {
  slug: string;
  draft: GuildSettings;
  channels: Channel[];
  roles: Role[];
  bots: BumpBot[];
  overview: GuildOverview | null;
}

/**
 * The settings form must survive anything the overview endpoint does.
 *
 * The types say every field is there once a section is non-null, but the
 * endpoint is new. If a section comes back a shape short, this column goes
 * quiet instead of taking the whole page down with it.
 */
class ContextBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="ov-card ov-card--quiet">
          <p className="ov-muted" style={{ margin: 0 }}>
            Live details could not be shown right now. Your settings are unaffected.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function ContextColumn(props: ContextProps) {
  return (
    <ContextBoundary>
      <ContextBody {...props} />
    </ContextBoundary>
  );
}

function ContextBody({ slug, draft, channels, roles, bots, overview }: ContextProps) {
  const bumps = overview?.bumps ?? null;
  const changes = overview?.changes ?? null;

  if (slug === "bumps") {
    const rows: [string, string][] = [
      ["Bump channel", channelName(channels, draft.bump_channel || "")],
      ["Reminder role", roleName(roles, draft.bump_role || "")],
      ["Bots tracked", String((draft.enabled_bots ?? []).length)],
    ];
    if (bumps) {
      rows.push([
        "Last bump seen",
        bumps.last_bump !== null ? formatRelative(bumps.last_bump, bumps.now) : "Never",
      ]);
      rows.push([
        "Next due",
        bumps.next_due !== null ? formatCountdown(bumps.next_due, bumps.now) : "Nothing waiting",
      ]);
    }
    return (
      <KvCard
        title="Right now"
        rows={rows}
        footer={
          "The bot only watches the bump channel. It reads messages there to spot a bump bot's" +
          " success message, and nothing anywhere else."
        }
      />
    );
  }

  if (slug === "bots") {
    const enabled = new Set(draft.enabled_bots ?? []);
    const rows: [string, string][] = bots.map((bot) => {
      if (!enabled.has(bot.key)) return [bot.name, "Not tracked"];
      const live = bumps?.bots.find((b) => b.key === bot.key);
      if (!live) return [bot.name, "Tracked"];
      if (live.last_bump === null) return [bot.name, "No bump seen yet"];
      return [
        bot.name,
        live.status === "ready"
          ? "Ready now"
          : live.next_due !== null
            ? formatCountdown(live.next_due, bumps?.now ?? live.next_due)
            : "On cooldown",
      ];
    });
    return (
      <KvCard
        title="Bump bots"
        rows={rows}
        footer="Untick a service and its timer stops - nothing is deleted, and its last bump is remembered if you turn it back on."
      />
    );
  }

  if (slug === "cooldowns") {
    const enabled = new Set(draft.enabled_bots ?? []);
    const delays = draft.bot_delay ?? {};
    const rows: [string, string][] = bots.map((bot) => {
      const fallback = bot.default_cooldown;
      const current = Number(delays[bot.key] ?? fallback ?? 0);
      const label = current ? formatDuration(current) : "Standard";
      if (!enabled.has(bot.key)) return [bot.name, `${label} (not tracked)`];
      if (fallback !== undefined && current !== fallback) return [bot.name, `${label} (changed)`];
      return [bot.name, label];
    });
    return (
      <KvCard
        title="Waiting time"
        rows={rows}
        footer={"This is how long the bot waits before saying a service is ready. It does not change the listing service's own cooldown."}
      />
    );
  }

  if (slug === "timers") {
    const rows: [string, string][] = [
      ["Countdown message", onOff(!!draft.timers_message)],
      ["Timers channel", channelName(channels, draft.timers_channel || "")],
    ];
    return (
      <KvCard
        title="Right now"
        rows={rows}
        footer={
          "The countdown is one message the bot keeps editing, so the channel does not fill up" +
          " with updates."
        }
      />
    );
  }

  if (slug === "message") {
    const text = (draft.custom_message ?? "").trim();
    const rows: [string, string][] = [
      ["Message written", text ? "Yes" : "No"],
      ["Length", `${(draft.custom_message ?? "").length} characters`],
    ];
    rows.push(["Being sent", text ? "Your wording" : "The standard reminder"]);
    return (
      <KvCard
        title="Right now"
        rows={rows}
        footer={"Use {bump_role} where the ping should go and {bots} for the list of bump bots."}
      />
    );
  }

  if (slug === "access") {
    const rows: [string, string][] = [
      ["Manager roles", String((draft.roles?.admin_role_ids ?? []).length)],
      ["Manage Server", "Always allowed"],
    ];
    if (changes) {
      rows.push(["Changes recorded", String(changes.total)]);
    }
    const recent = changes?.recent ?? [];
    return (
      <>
        <KvCard
          title="Who can manage"
          rows={rows}
          footer="Anyone with these roles gets the same access as Manage Server, here and in Discord."
        />
        {recent.length > 0 && (
          <div className="ov-card">
            <div className="ov-card__head">
              <span className="ov-card__title">Last changes</span>
            </div>
            <div className="ov-queue">
              {recent.slice(0, 5).map((entry, index) => (
                <div className="ov-qrow" key={`${entry.at ?? "unknown"}-${index}`}>
                  <span className="ov-qrow__txt">{changeLabel(entry)}</span>
                  <span className="ov-qrow__meta">{entry.actor ?? "unknown"}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </>
    );
  }

  return null;
}
