/** Bot-owned formatting for bump timings and the change log.
 *
 * The engine's `format.ts` covers ISO timestamps; ImperialReminder stores bump
 * times as unix SECONDS (integers), so the duration helpers below stay here.
 * They are the ones the bump cards have always used - lifted out of
 * BumpStatusGrid unchanged so the overview tiles can share them.
 */

import type { ChangeEntry } from "../../api/types";

/** Format a duration in seconds as a compact human string (e.g. "1h 30m"). */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  if (m > 0) return sec > 0 ? `${m}m ${sec}s` : `${m}m`;
  return `${sec}s`;
}

/** "3h ago" / "just now" relative to the supplied current unix time. */
export function formatRelative(unixSec: number, now: number): string {
  const diff = now - unixSec;
  if (diff < 60) return "just now";
  return `${formatDuration(diff)} ago`;
}

/** "in 1h 30m" / "due now" for a future unix time. */
export function formatCountdown(unixSec: number, now: number): string {
  const diff = unixSec - now;
  if (diff <= 0) return "due now";
  return `in ${formatDuration(diff)}`;
}

/** A settings-word out of a stored key: "bump_channel" -> "bump channel". */
function humanize(value: string): string {
  return value.replace(/[._]/g, " ").trim();
}

/**
 * One audit entry as a sentence.
 *
 * Entries arrive in two shapes: the admin panel writes
 * `action: "set:core.bump_channel"` with `details.section`/`details.key`, while
 * the retired premium cog wrote `action: "grant"` with a category
 * (historical rows still render). Both are handled,
 * and anything unrecognised falls back to the raw action rather than being
 * dropped - an unexplained entry still tells an admin that something changed.
 */
export function changeLabel(entry: ChangeEntry): string {
  const [verb, tail] = entry.action.includes(":")
    ? [entry.action.slice(0, entry.action.indexOf(":")), entry.action.slice(entry.action.indexOf(":") + 1)]
    : [entry.action, ""];
  const target = entry.key || tail || entry.section;
  const words = target ? `${humanize(verb)} ${humanize(target)}` : humanize(verb);
  const trimmed = words.trim();
  if (!trimmed) return "Setting changed";
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}
