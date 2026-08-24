import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, discordLoginUrl } from "../api/client";
import type { ScopeGuild, User, UserDataSummary } from "../api/types";
import type { Guild as PickerGuild } from "../_engine/api/types";
import { formatError } from "../_engine/api/formatError";
import ServerPicker from "../_engine/components/overview/ServerPicker";
import { KeyValue, Rule, Tile } from "../_engine/components/overview/Tile";
import AppHeader from "../components/AppHeader";

/*
 * Privacy and data - the member's own control panel.
 *
 * There are deliberately NO data-collection switches on this page, and that is
 * not an omission. Imperial Reminder has nothing per-member to collect: it
 * tracks servers, not people. The only records that name a person are the audit
 * entries written when they change a server's settings, and those are the
 * server's record of its own history - a switch that let an admin stop their
 * changes being recorded would be a governance hole, not a privacy feature.
 * The page says what is stored, counts it live, and offers export and erasure.
 *
 * Scope covers export, erasure AND the inventory: all three answer for the same
 * set of records, so showing a count for one scope beside buttons that act on
 * another would be the easiest possible way to mislead somebody here.
 */

export default function PrivacyPage() {
  const [user, setUser] = useState<User | null>(null);
  const [checkedAuth, setCheckedAuth] = useState(false);
  const [guilds, setGuilds] = useState<ScopeGuild[]>([]);
  const [guildsFailed, setGuildsFailed] = useState(false);
  const [scopeGuildId, setScopeGuildId] = useState<string | null>(null);

  const [summary, setSummary] = useState<UserDataSummary | null>(null);
  const [summaryFailed, setSummaryFailed] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [eraseResult, setEraseResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .me()
      .then((me) => {
        if (!alive) return;
        setUser(me);
        setCheckedAuth(true);
        return api.userGuilds(true);
      })
      .then((list) => {
        if (!alive || !list) return;
        setGuilds(list);
        setGuildsFailed(false);
      })
      .catch(() => {
        if (!alive) return;
        setCheckedAuth(true);
        setGuildsFailed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  // The inventory follows the scope picker, and is refetched after an erasure
  // so the numbers on the page are never the ones from before the click.
  const [inventoryTick, setInventoryTick] = useState(0);
  useEffect(() => {
    if (!user) return;
    let alive = true;
    setSummaryLoading(true);
    setSummaryFailed(false);
    api
      .userDataSummary(scopeGuildId)
      .then((s) => {
        if (alive) setSummary(s);
      })
      .catch(() => {
        if (!alive) return;
        setSummary(null);
        setSummaryFailed(true);
      })
      .finally(() => {
        if (alive) setSummaryLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [user, scopeGuildId, inventoryTick]);

  const scopeGuild = useMemo(
    () => guilds.find((g) => g.id === scopeGuildId) ?? null,
    [guilds, scopeGuildId],
  );
  const scopeLabel = scopeGuild ? scopeGuild.name ?? `Server ${scopeGuild.id}` : "all servers";

  // ServerPicker speaks the shared Guild shape. Every server in this list is one
  // that already holds a record of yours, so there is no setup state to carry.
  const pickerGuilds: PickerGuild[] = useMemo(
    () =>
      guilds.map((g) => ({
        id: g.id,
        name: g.name ?? `Server ${g.id}`,
        icon: g.icon,
        bot_in_guild: true,
        has_config: true,
        setup_required: false,
      })),
    [guilds],
  );

  const scopeMeta = scopeGuild
    ? "Counting, export and erase cover this server only"
    : guilds.length === 0
      ? "No server holds a record naming you yet"
      : guilds.length === 1
        ? "Counting, export and erase cover your one server"
        : `Counting, export and erase cover all ${guilds.length} of your servers`;

  async function runErase() {
    setError(null);
    setEraseResult(null);
    setErasing(true);
    try {
      const r = await api.deleteUserData(scopeGuildId);
      const total = Object.values(r.deleted).reduce((a, n) => a + n, 0);
      const where = scopeGuild ? `in ${scopeLabel}` : "across all servers";
      setEraseResult(
        total === 0
          ? `Nothing to erase ${where} - no records name you.`
          : `Removed your name and ID from ${total} record${total === 1 ? "" : "s"} ${where}.`,
      );
      setConfirmOpen(false);
      setInventoryTick((n) => n + 1);
      try {
        setGuilds(await api.userGuilds(true));
      } catch {
        // The scope list is a convenience; a stale one must not turn a
        // successful erasure into an error message.
      }
    } catch (e) {
      setError(formatError(e, "Your data could not be erased."));
      setConfirmOpen(false);
    } finally {
      setErasing(false);
    }
  }

  function countLabel(value: number | null | undefined): string {
    if (summaryLoading) return "Counting...";
    if (summaryFailed || value === null || value === undefined) return "Could not be counted";
    return String(value);
  }

  return (
    <div className="app-layout privacy-page">
      <AppHeader user={user} />

      <section className="dash-hero">
        <div className="dash-hero__orb" />
        <img className="dash-hero__sigil" src="/brand/artifact-belltower.svg" alt="" />
        <div className="dash-hero__copy">
          <span className="dash-hero__eyebrow">Account Control</span>
          <h1 className="dash-hero__title">Privacy &amp; Data</h1>
          <p className="dash-hero__sub">
            What Imperial Reminder stores, and how to take it back.
          </p>
        </div>
      </section>

      <div className="page">
        {error && (
          <div className="alert danger" role="alert" style={{ marginTop: 16 }}>
            {error}
          </div>
        )}

        <h2 className="section-title" style={{ margin: "24px 0 12px" }}>
          What is recorded
        </h2>

        <div className="ov-grid">
          <Tile span={12} title="What Imperial Reminder records about you">
            <p className="ov-body">
              Imperial Reminder is a bump-reminder bot. It tracks <strong>servers</strong>, not
              members - no messages, no activity, no profiles, no stats and no leaderboards.
              There is nothing per-member to switch off, which is why this page has no
              collection switches on it.
            </p>
            <p className="ov-body">
              For each server it keeps only the setup: which listing services to watch and when
              each was last bumped, the bump channel, the role to ping, the timers channel, an
              optional custom reminder wording, and which roles may change all of that. None of
              that names you.
            </p>
            <p className="ov-muted">
              The bot reads messages in the bump channel so it can recognise a listing service's
              success message. That text is never written to the database and is never tied to
              your account.
            </p>

            <Rule />

            <span className="ov-card__title">Records that do name you, in {scopeLabel}</span>
            {user ? (
              <>
                <div>
                  <KeyValue
                    k="Settings changes recorded against you"
                    v={countLabel(summary?.audit_log_entries)}
                  />
                </div>
                {summaryFailed && (
                  <p className="ov-muted">
                    These counts could not be read just now, so they are unknown rather than
                    zero. Reload the page to try again.
                  </p>
                )}
                <p className="ov-muted">
                  Records you have already erased are not in these counts: erasing removes your
                  name and ID from them, so they no longer name you and can no longer be found
                  by looking you up.
                </p>
              </>
            ) : (
              <p className="ov-muted">
                Sign in to count the records tied to your own account.
              </p>
            )}

            <Rule />

            <span className="ov-card__title">Signing in</span>
            <p className="ov-muted">
              Logging in uses Discord to confirm who you are and which servers you can manage.
              That sign-in session is shared across the Empire of Shadows dashboards and expires
              on its own. Logging out clears it.
            </p>
          </Tile>
        </div>

        {!user && checkedAuth && (
          <div className="ov-grid">
            <Tile span={12} quiet title="Your data">
              <p className="ov-body">
                Sign in with Discord to export or erase the records tied to your account.
              </p>
              <div className="admin-actions">
                <a className="btn btn-primary" href={discordLoginUrl("/me/privacy")}>
                  Sign in with Discord
                </a>
              </div>
            </Tile>
          </div>
        )}

        {user && (
          <>
            <h2 className="section-title" style={{ margin: "28px 0 0" }}>
              Export and erase
            </h2>

            <div className="ov-command">
              <ServerPicker
                guilds={pickerGuilds}
                selectedGuildId={scopeGuildId}
                onSelect={(id) => {
                  setScopeGuildId(id);
                  setEraseResult(null);
                  setError(null);
                }}
                meta={scopeMeta}
              />
              <span className="ov-muted">
                One choice for the count above and both tiles below. Only servers that actually
                hold a record of yours are listed.
              </span>
            </div>

            {guildsFailed && (
              <p className="ov-muted">
                Your server list could not be loaded, so only the all-servers option is
                available here. Reload the page to try again.
              </p>
            )}
            {!guildsFailed && guilds.length === 0 && (
              <p className="ov-muted">
                No server currently holds a record naming you, so there is nothing to pick
                between - export and erase cover everything, which is nothing.
              </p>
            )}

            <div className="ov-grid">
              <Tile span={6} title="Export your data">
                <p className="ov-body">
                  Download a JSON file with everything Imperial Reminder holds against your
                  account in {scopeLabel}:
                </p>
                <ul className="ov-body" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  <li>
                    Every settings change recorded against you - what changed, what it was, what
                    it became, and when
                  </li>
                </ul>
                <div className="admin-actions">
                  <a
                    href={api.exportUserDataUrl(scopeGuildId)}
                    className="btn btn-secondary"
                    download
                  >
                    Download my data
                  </a>
                </div>
              </Tile>

              <Tile span={6} title="Erase your data">
                <p className="ov-body">
                  Strips your name and Discord ID from every settings change recorded against
                  you in {scopeLabel}. This cannot be undone.
                </p>

                <Rule />

                <span className="ov-card__title">What stays behind</span>
                <ul className="ov-body" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  <li>
                    The change records themselves. They are the server's history of what was
                    changed and when, which its managers rely on, so they are redacted rather
                    than deleted - the entry survives, it just no longer points at you.
                  </li>
                  <li>
                    Changes you make from this dashboard after erasing, which are recorded the
                    same way as any other.
                  </li>
                </ul>

                <div className="admin-actions">
                  <button
                    type="button"
                    className="btn btn-danger"
                    disabled={erasing}
                    onClick={() => {
                      setEraseResult(null);
                      setError(null);
                      setConfirmOpen(true);
                    }}
                  >
                    {erasing ? "Erasing..." : "Erase my data..."}
                  </button>
                </div>

                {eraseResult && (
                  <p style={{ color: "var(--success)", margin: 0 }} role="status">
                    {eraseResult}
                  </p>
                )}
              </Tile>
            </div>
          </>
        )}

        <p className="ov-muted" style={{ margin: "20px 0 28px" }}>
          The full <Link to="/privacy">privacy policy</Link> explains what Imperial Reminder
          stores and why.
        </p>
      </div>

      {confirmOpen && (
        <EraseConfirm
          scopeLabel={scopeLabel}
          erasing={erasing}
          onConfirm={() => void runErase()}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </div>
  );
}

/**
 * Type-DELETE confirmation for the erase button.
 *
 * Written here rather than reached for from ConfirmDialog because that shared
 * dialog has no typed-confirmation step. Everything it does have is kept: the
 * same .confirm-* markup, focus moved into the dialog on open and handed back
 * to whatever opened it on close, and Escape or a backdrop click cancelling.
 * Tab is additionally kept inside the dialog, which matters more here than on a
 * one-button confirm.
 *
 * Mounted only while open, so each opening starts with an empty box.
 */
function EraseConfirm({
  scopeLabel,
  erasing,
  onConfirm,
  onCancel,
}: {
  scopeLabel: string;
  erasing: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const previousActive = useRef<HTMLElement | null>(null);
  // Held in a ref so the key handler is installed once on open. The parent
  // passes a fresh closure every render; depending on it would re-run the
  // effect mid-typing and steal focus back to the input.
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;

  useEffect(() => {
    previousActive.current = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        cancelRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      // Rebuilt on every Tab because the confirm button is disabled until the
      // word is typed, and a disabled control must not be a stop in the cycle.
      const stops = Array.from(
        dialog.querySelectorAll<HTMLElement>("input, button"),
      ).filter((node) => !node.hasAttribute("disabled"));
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      const active = document.activeElement;
      if (!dialog.contains(active)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previousActive.current?.focus?.();
    };
    // Runs once for the lifetime of one opening; the cancel closure is a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const armed = text === "DELETE" && !erasing;

  return (
    <div
      className="confirm-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="privacy-erase-title"
      aria-describedby="privacy-erase-message"
      onClick={onCancel}
    >
      <div className="confirm-dialog" ref={dialogRef} onClick={(e) => e.stopPropagation()}>
        <h2 id="privacy-erase-title" className="confirm-title">
          Erase your data in {scopeLabel}?
        </h2>
        <p id="privacy-erase-message" className="confirm-message">
          This removes your name and Discord ID from every settings change recorded against you
          in {scopeLabel}. The change records stay so the server keeps its history. This
          cannot be undone.
        </p>

        <div className="eos-field">
          <label htmlFor="privacy-erase-confirm">Type DELETE to confirm</label>
          <input
            id="privacy-erase-confirm"
            ref={inputRef}
            type="text"
            value={text}
            disabled={erasing}
            autoComplete="off"
            placeholder="DELETE"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && armed) onConfirm();
            }}
          />
        </div>

        <div className="confirm-actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={erasing}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button type="button" className="btn btn-danger" disabled={!armed} onClick={onConfirm}>
            {erasing ? "Erasing..." : "Erase everything"}
          </button>
        </div>
      </div>
    </div>
  );
}
