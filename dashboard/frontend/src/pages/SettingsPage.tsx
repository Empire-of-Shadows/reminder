import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  BumpBot,
  Channel,
  GuildOverview,
  GuildSettings,
  Role,
  SettingsPatch,
} from "../api/types";
import { formatError } from "../_engine/api/formatError";
import {
  ChannelField,
  Fieldset,
  FRow,
  MultiOptionField,
  MultiRoleField,
  OptionSelect,
  PickerStatusProvider,
  RoleField,
  TextareaField,
  ToggleField,
} from "../_engine/components/settings/fields";
import AppHeader from "../components/AppHeader";
import ConfirmDialog from "../components/ConfirmDialog";
import PageSkeleton from "../components/PageSkeleton";
import ContextColumn from "../components/settings/ContextColumn";
import { formatDuration } from "../components/overview/format";

/*
 * Per-guild settings.
 *
 * The four full-width cards this replaced sat in one uncapped column, so a
 * single dropdown got a box as wide as the monitor. The layout is the shared
 * engine one: a rail with a search box, a reading-width form column, and a
 * context column showing what the selected setting is actually doing.
 *
 * The save model changed on purpose. One Save button used to send every field
 * on the page, so opening Settings to change the reminder role also rewrote the
 * custom message, the bot list and the manager roles - and the savebar said so
 * ("Saving writes every section on this page"), which is a warning where a
 * design would do. Each rail section now owns its own Save button, its own
 * dirty state and its own Unsaved badge, and saving one leaves unsaved edits in
 * the others exactly where they were. Moving away from a section with unsaved
 * edits asks first.
 */

type Slug = "bumps" | "bots" | "cooldowns" | "timers" | "message" | "access";

/** The settings keys each rail section owns. Saving a section sends these and
 *  nothing else, and the server's reply is merged back over these alone. */
const SECTION_KEYS: Record<Slug, string[]> = {
  bumps: ["bump_channel", "bump_role"],
  bots: ["enabled_bots"],
  cooldowns: ["bot_delay"],
  timers: ["timers_channel", "timers_message"],
  message: ["custom_message"],
  access: ["roles"],
};

interface RailItem {
  slug: Slug;
  /** Rail label. */
  label: string;
  /** Heading over the form column. */
  title: string;
  /** Plain-language description of what this does for the server. */
  blurb: string;
  /** Label on this section's Save button. */
  saveLabel: string;
  /** Field labels and help text, for the rail search box. */
  search: string[];
}

const RAIL_GROUPS: { name: string; items: RailItem[] }[] = [
  {
    name: "Reminders",
    items: [
      {
        slug: "bumps",
        label: "Bumping",
        title: "Bumping",
        blurb:
          "The channel you bump in, and the role the bot pings when it is time to bump again. Without both of these there is nothing to watch and nobody to tell.",
        saveLabel: "Save bumping",
        search: ["Bump channel", "Reminder role", "Role to ping", "Where you bump"],
      },
      {
        slug: "bots",
        label: "Bump bots",
        title: "Bump bots to track",
        blurb:
          "The listing services this server bumps on. The bot only times the ones you tick here, so leave out anything you do not use.",
        saveLabel: "Save bump bots",
        search: ["Disboard", "BumpIt", "Bump4You", "WeBump", "OneBump", "Unfocused", "Services"],
      },
      {
        slug: "cooldowns",
        label: "Cooldowns",
        title: "How long between bumps",
        blurb:
          "How long the bot waits before telling you a service can be bumped again. Most services have one fixed cooldown and nothing to choose; a couple offer a shorter wait.",
        saveLabel: "Save cooldowns",
        search: [
          "Cooldown",
          "Delay",
          "How often",
          "Wait",
          "30 minutes",
          "90 minutes",
        ],
      },
      {
        slug: "timers",
        label: "Live countdown",
        title: "Live countdown",
        blurb:
          "An optional message the bot keeps up to date with how long is left on each bump, so anyone can check without asking.",
        saveLabel: "Save countdown",
        search: ["Timers channel", "Countdown", "Timer message"],
      },
      {
        slug: "message",
        label: "Reminder wording",
        title: "Custom reminder message",
        blurb:
          "Replace the standard reminder with your own wording. Once saved, it is what the bot sends.",
        saveLabel: "Save wording",
        search: ["Custom message", "Wording", "bump_role", "bots"],
      },
    ],
  },
  {
    name: "Access",
    items: [
      {
        slug: "access",
        label: "Who can manage",
        title: "Who can manage",
        blurb:
          "Members holding any of these roles get the same access to this dashboard and the in-Discord admin panel as someone with Manage Server. Everyone else sees nothing here.",
        saveLabel: "Save manager roles",
        search: ["Panel access", "Admin roles", "Permissions", "Manage Server"],
      },
    ],
  },
];

const RAIL_ITEMS: RailItem[] = RAIL_GROUPS.flatMap((g) => g.items);

const DEFAULT_SLUG: Slug = "bumps";

/** Terms that reach the change-history link in the rail search. */
const HISTORY_SEARCH = [
  "Change history",
  "Audit log",
  "Who changed a setting and when",
];

function parseSlug(raw: string | null): Slug {
  const hit = RAIL_ITEMS.find((i) => i.slug === raw);
  return hit ? hit.slug : DEFAULT_SLUG;
}

/**
 * A section's values, normalized so the dirty check answers the question a
 * person would ask. Sorting the lists means reordering a role picker is not
 * reported as an edit, and the ?? defaults mean a missing key and an empty one
 * compare equal.
 */
function sectionSnapshot(slug: Slug, s: GuildSettings): string {
  switch (slug) {
    case "bumps":
      return JSON.stringify([s.bump_channel || "", s.bump_role || ""]);
    case "bots":
      return JSON.stringify([...(s.enabled_bots ?? [])].sort());
    case "cooldowns":
      return JSON.stringify(
        Object.entries(s.bot_delay ?? {})
          .map(([k, v]) => [k, Number(v)] as [string, number])
          .sort((a, b) => a[0].localeCompare(b[0])),
      );
    case "timers":
      return JSON.stringify([s.timers_channel || "", !!s.timers_message]);
    case "message":
      return JSON.stringify(s.custom_message ?? "");
    case "access":
      return JSON.stringify([...(s.roles?.admin_role_ids ?? [])].sort());
  }
}

/** The patch one section sends. Only its own keys, in the wire shape. */
function sectionPatch(slug: Slug, s: GuildSettings): SettingsPatch {
  switch (slug) {
    case "bumps":
      return { bump_channel: s.bump_channel || "", bump_role: s.bump_role || "" };
    case "bots":
      return { enabled_bots: s.enabled_bots ?? [] };
    case "cooldowns":
      return { bot_delay: s.bot_delay ?? {} };
    case "timers":
      return {
        timers_channel: s.timers_channel || "",
        timers_message: !!s.timers_message,
      };
    case "message":
      return { custom_message: s.custom_message ?? "" };
    case "access":
      return { roles: { admin_role_ids: s.roles?.admin_role_ids ?? [] } };
  }
}

type BadgeTone = "ok" | "warn" | "";

interface Badge {
  text: string;
  tone: BadgeTone;
}

/**
 * What the rail badge says about a section.
 *
 * "Set up" is the load-bearing one: switched on but missing something it cannot
 * run without, which is the state that looks fine and silently does nothing.
 */
function railBadge(slug: Slug, d: GuildSettings, bots: BumpBot[]): Badge {
  switch (slug) {
    case "bumps":
      if (!d.bump_channel) return { text: "Set up", tone: "warn" };
      return d.bump_role ? { text: "On", tone: "ok" } : { text: "Set up", tone: "warn" };
    case "bots": {
      const count = (d.enabled_bots ?? []).length;
      return count > 0 ? { text: String(count), tone: "ok" } : { text: "Set up", tone: "warn" };
    }
    case "cooldowns": {
      const delays = d.bot_delay ?? {};
      const changed = bots.filter((bot) => {
        const fallback = bot.default_cooldown;
        if (fallback === undefined) return false;
        const current = Number(delays[bot.key] ?? fallback);
        return current !== fallback;
      }).length;
      return changed > 0 ? { text: "Custom", tone: "ok" } : { text: "Default", tone: "" };
    }
    case "timers":
      if (!d.timers_message) return { text: "Off", tone: "" };
      return d.timers_channel ? { text: "On", tone: "ok" } : { text: "Set up", tone: "warn" };
    case "message":
      return (d.custom_message ?? "").trim()
        ? { text: "Written", tone: "ok" }
        : { text: "Default", tone: "" };
    case "access": {
      const count = (d.roles?.admin_role_ids ?? []).length;
      return { text: String(count), tone: count > 0 ? "ok" : "" };
    }
  }
}

export default function SettingsPage() {
  const { guildId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [channelsFailed, setChannelsFailed] = useState(false);
  const [rolesFailed, setRolesFailed] = useState(false);
  const [bots, setBots] = useState<BumpBot[]>([]);
  const [lastSaved, setLastSaved] = useState<GuildSettings | null>(null);
  const [settings, setSettings] = useState<GuildSettings | null>(null);
  const [overview, setOverview] = useState<GuildOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingSlug, setSavingSlug] = useState<Slug | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [pendingSlug, setPendingSlug] = useState<Slug | null>(null);

  const slug = parseSlug(searchParams.get("s"));

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const s = await api.settings(guildId);
        if (!alive) return;
        setSettings(s);
        setLastSaved(s);
      } catch (e) {
        if (alive) setError(formatError(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();

    // The channel and role lists load separately from the settings, so a
    // permission problem on one of them cannot blank the whole page. When one
    // fails the picker says so instead of showing an empty dropdown that reads
    // as "this server has no channels".
    api
      .getChannels(guildId)
      .then((c) => {
        if (!alive) return;
        setChannels(c);
        setChannelsFailed(false);
      })
      .catch(() => {
        if (!alive) return;
        setChannels([]);
        setChannelsFailed(true);
      });

    api
      .getRoles(guildId)
      .then((r) => {
        if (!alive) return;
        setRoles([...r].sort((a, b) => b.position - a.position));
        setRolesFailed(false);
      })
      .catch(() => {
        if (!alive) return;
        setRoles([]);
        setRolesFailed(true);
      });

    api.bumpBots().then((b) => { if (alive) setBots(b); }).catch(() => {});

    // Optional. The context column drops the rows it cannot fill.
    api.guildOverview(guildId).then((o) => { if (alive) setOverview(o); }).catch(() => {
      if (alive) setOverview(null);
    });

    return () => {
      alive = false;
    };
  }, [guildId]);

  const enabled = useMemo(() => new Set(settings?.enabled_bots ?? []), [settings]);

  function update<K extends keyof GuildSettings>(key: K, value: GuildSettings[K]) {
    setSettings((s) => (s ? { ...s, [key]: value } : s));
    setSaved(null);
  }

  function setCooldown(botKey: string, seconds: number) {
    setSettings((s) =>
      s ? { ...s, bot_delay: { ...(s.bot_delay ?? {}), [botKey]: seconds } } : s,
    );
    setSaved(null);
  }

  const isDirty = (target: Slug): boolean =>
    !!settings &&
    !!lastSaved &&
    sectionSnapshot(target, settings) !== sectionSnapshot(target, lastSaved);

  async function save(target: Slug) {
    if (!settings) return;
    setSavingSlug(target);
    setError(null);
    setSaved(null);
    try {
      const updated = await api.saveSettings(guildId, sectionPatch(target, settings));
      // The reply is the canonical whole config, so it becomes the new saved
      // baseline. Only this section's keys are merged into the draft, which is
      // what keeps unsaved edits elsewhere on the page intact.
      setLastSaved(updated);
      setSettings((prev) => {
        if (!prev) return updated;
        const merged = { ...prev };
        for (const key of SECTION_KEYS[target]) {
          merged[key] = updated[key];
        }
        return merged;
      });
      setSaved(RAIL_ITEMS.find((i) => i.slug === target)?.title ?? "Settings");
    } catch (e) {
      setError(formatError(e));
    } finally {
      setSavingSlug(null);
    }
  }

  if (loading) return <PageSkeleton />;

  const active = RAIL_ITEMS.find((i) => i.slug === slug) ?? RAIL_ITEMS[0];
  const activeDirty = isDirty(active.slug);

  const goTo = (next: Slug) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        params.set("s", next);
        return params;
      },
      { replace: true },
    );
  };

  const requestSlug = (next: Slug) => {
    if (next === slug) return;
    if (activeDirty) {
      setPendingSlug(next);
      return;
    }
    goTo(next);
  };

  const q = query.trim().toLowerCase();
  const itemMatches = (item: RailItem): boolean => {
    if (!q) return true;
    if (item.label.toLowerCase().includes(q)) return true;
    if (item.title.toLowerCase().includes(q)) return true;
    return item.search.some((s) => s.toLowerCase().includes(q));
  };
  const historyMatches = !q || HISTORY_SEARCH.some((s) => s.toLowerCase().includes(q));
  const anyMatch = RAIL_ITEMS.some(itemMatches) || historyMatches;

  // Only the services that actually offer a choice get a dropdown. A select
  // with one option is a control that cannot be operated.
  const adjustable = bots.filter((bot) => (bot.choices?.length ?? 0) > 1);
  const fixed = bots.filter((bot) => (bot.choices?.length ?? 0) <= 1);

  return (
    <div className="app-layout">
      <AppHeader
        title="Server Settings"
        left={
          <Link to="/dashboard" className="btn btn-secondary" style={{ marginLeft: 12 }}>
            &larr; Servers
          </Link>
        }
      />

      <div className="page">
        {error && (
          <div className="alert danger" role="alert" style={{ marginTop: 16 }}>
            {error}
          </div>
        )}
        {saved && (
          <div className="alert success" role="status" style={{ marginTop: 16 }}>
            {saved} saved.
          </div>
        )}

        {settings && (
          <div className="set-layout">
            <div>
              <div className="set-search">
                <span className="set-search__i" aria-hidden="true">
                  &#8981;
                </span>
                <input
                  type="search"
                  value={query}
                  placeholder="Search settings"
                  aria-label="Search settings"
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>

              <nav className="set-rail" aria-label="Settings sections">
                {RAIL_GROUPS.map((group) => {
                  const items = group.items.filter(itemMatches);
                  const showHistory = group.name === "Access" && historyMatches;
                  if (items.length === 0 && !showHistory) return null;
                  return (
                    <Fragment key={group.name}>
                      <div className="set-rail__grp">{group.name}</div>
                      {items.map((item) => {
                        const dirty = isDirty(item.slug);
                        const badge = dirty
                          ? { text: "Unsaved", tone: "warn" as BadgeTone }
                          : railBadge(item.slug, settings, bots);
                        return (
                          <button
                            key={item.slug}
                            type="button"
                            className={
                              "set-rail__item" + (item.slug === slug ? " is-active" : "")
                            }
                            aria-current={item.slug === slug ? "page" : undefined}
                            onClick={() => requestSlug(item.slug)}
                          >
                            <span>{item.label}</span>
                            <span
                              className={
                                "set-rail__badge" +
                                (badge.tone ? ` set-rail__badge--${badge.tone}` : "")
                              }
                            >
                              {badge.text}
                            </span>
                          </button>
                        );
                      })}
                      {showHistory && (
                        <Link
                          className="set-rail__item"
                          to={`/settings/${guildId}/audit-log`}
                        >
                          <span>Change history</span>
                        </Link>
                      )}
                    </Fragment>
                  );
                })}
                {!anyMatch && (
                  <p className="set-rail__empty">Nothing here matches "{query.trim()}".</p>
                )}
              </nav>
            </div>

            <PickerStatusProvider value={{ channelsFailed, rolesFailed }}>
              <div className="set-main">
                <div className="set-head">
                  <h1>{active.title}</h1>
                  <p>{active.blurb}</p>
                </div>

                {slug === "bumps" && (
                  <Fieldset>
                    <FRow>
                      <ChannelField
                        label="Bump channel"
                        value={settings.bump_channel || null}
                        channels={channels}
                        onChange={(v) => update("bump_channel", v ?? "")}
                        description="Where you run the bump commands. The bot watches only this channel."
                      />
                      <RoleField
                        label="Reminder role to ping"
                        value={settings.bump_role || null}
                        roles={roles}
                        onChange={(v) => update("bump_role", v ?? "")}
                        description="The only role the reminder is ever allowed to mention."
                      />
                    </FRow>
                  </Fieldset>
                )}

                {slug === "bots" && (
                  <Fieldset>
                    <MultiOptionField
                      label="Bump bots to track"
                      description="Reminders are only scheduled for the services ticked here."
                      value={bots.filter((b) => enabled.has(b.key)).map((b) => b.key)}
                      options={bots.map((b) => [b.key, b.name] as [string, string])}
                      onChange={(v) => update("enabled_bots", v)}
                    />
                  </Fieldset>
                )}

                {slug === "cooldowns" && (
                  <Fieldset>
                    {adjustable.length === 0 ? (
                      <p className="eos-muted">
                        {bots.length === 0
                          ? "The list of bump bots could not be loaded, so the cooldowns cannot be shown. Reload the page to try again."
                          : "None of the supported services offer a choice of cooldown, so there is nothing to set here."}
                      </p>
                    ) : (
                      <>
                        <FRow>
                          {adjustable.map((bot) => {
                            const current = Number(
                              settings.bot_delay?.[bot.key] ?? bot.default_cooldown ?? 0,
                            );
                            const options = (bot.choices ?? []).map(
                              (choice) =>
                                [choice.seconds, choice.label] as [number, string],
                            );
                            return (
                              <OptionSelect<number>
                                key={bot.key}
                                label={`${bot.name} cooldown`}
                                value={current}
                                options={options}
                                onChange={(v) => setCooldown(bot.key, v)}
                                description={`How long the bot waits after a ${bot.name} bump before it says the service is ready again.`}
                              />
                            );
                          })}
                        </FRow>
                      </>
                    )}
                    {fixed.length > 0 && (
                      <p className="eos-muted">
                        Fixed by the listing service, with nothing to choose:{" "}
                        {fixed
                          .map(
                            (bot) =>
                              `${bot.name} (${
                                bot.default_cooldown
                                  ? formatDuration(bot.default_cooldown)
                                  : "standard"
                              })`,
                          )
                          .join(", ")}
                        .
                      </p>
                    )}
                  </Fieldset>
                )}

                {slug === "timers" && (
                  <Fieldset>
                    <FRow full>
                      <ToggleField
                        label="Show a live countdown message"
                        value={!!settings.timers_message}
                        onChange={(v) => update("timers_message", v)}
                        description="The bot keeps one message updated with the time left on each bump."
                      />
                    </FRow>
                    <FRow full>
                      <ChannelField
                        label="Timers display channel"
                        value={settings.timers_channel || null}
                        channels={channels}
                        onChange={(v) => update("timers_channel", v ?? "")}
                        description="Optional. Leave unset to keep the countdown out of your server."
                      />
                    </FRow>
                  </Fieldset>
                )}

                {slug === "message" && (
                  <Fieldset>
                    <TextareaField
                      label="Custom reminder message"
                      value={settings.custom_message ?? ""}
                      rows={3}
                      onChange={(v) => update("custom_message", v)}
                      placeholder="It's time to bump! {bump_role} - {bots}"
                      description="Optional. {bump_role} becomes the ping and {bots} becomes the list of bump bots."
                    />
                  </Fieldset>
                )}

                {slug === "access" && (
                  <Fieldset>
                    <MultiRoleField
                      label="Manager roles"
                      description="Members with Manage Server can always manage this bot. Roles ticked here get the same full access, on this dashboard and on the in-Discord admin panel."
                      value={settings.roles?.admin_role_ids ?? []}
                      roles={roles}
                      onChange={(v) => update("roles", { admin_role_ids: v })}
                    />
                  </Fieldset>
                )}

                <div className="savebar">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={!activeDirty || savingSlug === active.slug}
                    onClick={() => void save(active.slug)}
                  >
                    {savingSlug === active.slug ? "Saving..." : active.saveLabel}
                  </button>
                  <span className="eos-muted" style={{ fontSize: 13 }}>
                    {activeDirty
                      ? "Unsaved changes. Saving writes only this section."
                      : "Everything here is saved"}
                  </span>
                </div>
              </div>
            </PickerStatusProvider>

            <aside className="set-ctx" aria-label="Current state">
              <ContextColumn
                slug={slug}
                draft={settings}
                channels={channels}
                roles={roles}
                bots={bots}
                overview={overview}
              />
            </aside>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pendingSlug !== null}
        title="You have unsaved changes"
        message={`"${active.title}" has changes you have not saved yet. They are kept while you move around this page, but they are lost if you reload or close it.`}
        confirmLabel="Switch anyway"
        cancelLabel="Stay here"
        onConfirm={() => {
          const next = pendingSlug;
          setPendingSlug(null);
          if (next) goTo(next);
        }}
        onCancel={() => setPendingSlug(null)}
      />
    </div>
  );
}
