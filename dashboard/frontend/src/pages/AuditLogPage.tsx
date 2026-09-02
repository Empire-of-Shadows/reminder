import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AuditLogRow, AuditLogSummary } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { formatDuration } from "../components/overview/format";
import { formatDateTime, formatRelative } from "../_engine/format";
import { KeyValue, SectionUnavailable, Stat, Tile } from "../_engine/components/overview/Tile";
import AdminNav from "../components/AdminNav";
import AppHeader from "../components/AppHeader";
import PageSkeleton from "../components/PageSkeleton";

/*
 * Change history for one server.
 *
 * Every edit from the in-Discord admin panel and from this dashboard is
 * recorded, and both are shown here as the same kind of thing - the `Where`
 * column is the only difference between them. Entries are kept for a year and
 * then expire on their own.
 *
 * Deliberately a full page on the app shell rather than a bare table: an admin
 * reaches it from the settings rail and should not lose the header, the
 * navigation or the footer on the way.
 */

/** A stored value as one short readable cell.
 *
 *  `key` is passed in because a cooldown is stored as a number of seconds, and
 *  "7200" is not something an admin should have to convert in their head to
 *  check what they changed.
 */
function formatValue(value: unknown, key = ""): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "number") {
    return key.startsWith("bot_delay") ? formatDuration(value) : String(value);
  }
  if (typeof value === "string") return value.length > 60 ? `${value.slice(0, 57)}...` : value;
  try {
    const text = JSON.stringify(value);
    return text.length > 60 ? `${text.slice(0, 57)}...` : text;
  } catch {
    return String(value);
  }
}

/** "set" -> "Set", "bot_delay.disboard" -> "bot delay disboard". */
function humanize(value: string): string {
  const words = value.replace(/[._]/g, " ").trim();
  if (!words) return "";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function sourceLabel(source: string): string {
  if (source === "dashboard") return "This dashboard";
  if (source === "panel") return "Discord panel";
  return humanize(source);
}

export default function AuditLogPage() {
  const { guildId = "" } = useParams();
  const [entries, setEntries] = useState<AuditLogRow[]>([]);
  const [summary, setSummary] = useState<AuditLogSummary | null | undefined>(undefined);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const loadFirst = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.auditLog(guildId);
      setEntries(page.entries);
      setNextCursor(page.next_cursor);
      // `undefined` means the request never answered; `null` means the counts
      // themselves failed while the entries came back. They read differently.
      setSummary(page.summary ?? null);
    } catch (e) {
      setError(formatError(e, "The change history could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [guildId]);

  useEffect(() => {
    void loadFirst();
  }, [loadFirst]);

  async function loadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const page = await api.auditLog(guildId, nextCursor);
      setEntries((prev) => [...prev, ...page.entries]);
      setNextCursor(page.next_cursor);
    } catch (e) {
      setError(formatError(e, "No more entries could be loaded."));
    } finally {
      setLoadingMore(false);
    }
  }

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((entry) =>
      [entry.actor ?? "", entry.actor_id ?? "", entry.section, entry.key, entry.action]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [entries, query]);

  if (loading) return <PageSkeleton />;

  return (
    <div className="app-layout">
      <AppHeader title="Change history" />

      <div className="page">
        {/* The admin tab bar replaces the back button that used to sit in the
            header: Settings is one of its tabs, so the way back is still one
            click and it now says where else this server can be managed. */}
        <AdminNav guildId={guildId} />

        {error && (
          <div className="alert danger" role="alert" style={{ marginTop: 16 }}>
            {error}
          </div>
        )}

        <div className="ov-grid">
          <Tile span={4} title="Recorded here">
            {summary === undefined || summary === null ? (
              <SectionUnavailable what="The change totals" />
            ) : (
              <>
                <div className="ov-statrow">
                  <Stat value={summary.total} label="Changes recorded" />
                  <Stat
                    small
                    value={summary.total_window}
                    label={`In ${summary.window_days} days`}
                  />
                </div>
                <div>
                  <KeyValue
                    k="Newest change"
                    v={summary.newest ? formatRelative(summary.newest) : "None yet"}
                  />
                  <KeyValue k="Kept for" v="1 year" />
                </div>
              </>
            )}
            <p className="ov-muted">
              Every setting changed from the in-Discord panel or from this dashboard is
              recorded. Entries older than a year are removed automatically.
            </p>
          </Tile>

          <Tile
            span={8}
            title="Changes"
            chips={
              query.trim() ? (
                <span className="ov-chip">
                  {filtered.length} of {entries.length} loaded
                </span>
              ) : (
                <span className="ov-chip">{entries.length} loaded</span>
              )
            }
          >
            <div className="set-search" style={{ marginBottom: 12 }}>
              <span className="set-search__i" aria-hidden="true">
                &#8981;
              </span>
              <input
                type="search"
                value={query}
                placeholder="Filter by person or setting"
                aria-label="Filter the loaded changes"
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            {entries.length === 0 ? (
              <p className="ov-body">
                Nothing has been changed in this server yet. Every edit from the panel or this
                dashboard will be recorded here.
              </p>
            ) : filtered.length === 0 ? (
              <p className="ov-body">
                None of the {entries.length} changes loaded so far match "{query.trim()}". There
                may be older ones - load more below and search again.
              </p>
            ) : (
              <div className="audit-scroll">
                <table className="audit-table">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Who</th>
                      <th>Where</th>
                      <th>Setting</th>
                      <th>Was</th>
                      <th>Now</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((entry, index) => (
                      <tr key={`${entry.at ?? "unknown"}-${entry.key}-${index}`}>
                        <td className="audit-table__when">
                          {entry.at ? formatDateTime(entry.at) : "Unknown"}
                        </td>
                        <td title={entry.actor_id ?? undefined}>
                          {entry.actor ?? "Not recorded"}
                        </td>
                        <td>{sourceLabel(entry.source)}</td>
                        <td>
                          {humanize(entry.key || entry.section || entry.action) || "A setting"}
                        </td>
                        <td>
                          <code>{formatValue(entry.old_value, entry.key)}</code>
                        </td>
                        <td>
                          <code>{formatValue(entry.new_value, entry.key)}</code>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {nextCursor && (
              <div className="admin-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={loadingMore}
                  onClick={() => void loadMore()}
                >
                  {loadingMore ? "Loading..." : "Load older changes"}
                </button>
              </div>
            )}
          </Tile>
        </div>
      </div>
    </div>
  );
}
