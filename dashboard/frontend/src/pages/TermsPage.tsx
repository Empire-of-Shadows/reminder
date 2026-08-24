import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { User } from "../api/types";
import AppHeader from "../components/AppHeader";

/**
 * Public, unauthenticated terms of service.
 *
 * Same shape as the privacy policy next door - a `dash-hero` header over a
 * numbered `legal-doc` body - and it renders without a session, loading the
 * signed-in user only to personalise the header.
 */
const EFFECTIVE_DATE = "August 24, 2026";

export default function TermsPage() {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api.me().then(setUser).catch(() => {});
  }, []);

  return (
    <div className="app-layout">
      <AppHeader user={user} />

      <section className="dash-hero">
        <div className="dash-hero__orb" />
        <img className="dash-hero__sigil" src="/brand/artifact-belltower.svg" alt="" />
        <div className="dash-hero__copy">
          <span className="dash-hero__eyebrow">Legal</span>
          <h1 className="dash-hero__title">Terms of Service</h1>
          <p className="dash-hero__sub">Effective {EFFECTIVE_DATE}</p>
        </div>
      </section>

      <div className="legal-doc">
        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>1. Acceptance and eligibility</h2>
          <p>
            Imperial Reminder ("the bot", "we", "us") is a Discord bot and companion web
            dashboard operated as part of the Empire of Shadows ecosystem. By adding the bot to
            a server, using its commands, or signing in to the dashboard, you agree to these
            Terms of Service.
          </p>
          <p>
            You must meet Discord's minimum age requirement for your region and comply with the{" "}
            <a href="https://discord.com/terms" target="_blank" rel="noopener">
              Discord Terms of Service
            </a>{" "}
            at all times. If you do not agree to these terms, do not use the bot or the
            dashboard.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>2. The service</h2>
          <p>
            Imperial Reminder tracks when a server was last bumped on Discord server-listing
            services and reminds the server when it can bump again. To do that it reads messages
            in the one channel a server manager sets as the bump channel, so it can recognise a
            listing service's success message, and it mentions one role the manager chooses when
            a bump comes off cooldown. It can also keep a live countdown message up to date.
          </p>
          <p>
            The bot is designed to work in any Discord server, not only Empire of Shadows, and
            it is not affiliated with, endorsed by, or operated by any of the listing services
            it tracks. Their own cooldowns, rules and availability are theirs, not ours.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>3. Acceptable use</h2>
          <p>When using the bot or dashboard, you agree not to:</p>
          <ul>
            <li>
              Use the bot to evade, automate around, or otherwise break a listing service's own
              rules on how often a server may be bumped.
            </li>
            <li>Harass, abuse, or harm other members, including through reminder pings.</li>
            <li>
              Attempt to disrupt, overload, reverse engineer, or gain unauthorized access to the
              service.
            </li>
            <li>
              Use the service in violation of the Discord Terms of Service or the rules of the
              server you are in.
            </li>
          </ul>
          <p className="muted">
            Server administrators configure where and how the bot runs in their server, including
            which role is pinged, and may change or remove that setup at any time.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>4. Server configuration</h2>
          <p>
            Everything the bot stores for a server is configuration written by that server's
            managers: which listing services to watch, the bump channel, the role to ping, the
            timers channel, an optional custom reminder wording, and which roles may change
            those settings. Anyone with Manage Server, or a role a manager has granted access
            to, can view and change all of it from the in-Discord panel or this dashboard.
          </p>
          <p>
            Changes are recorded in a per-server history so managers can see who changed what.
            What we do and do not store about you personally is covered by the{" "}
            <Link to="/privacy">Privacy Policy</Link>.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>5. Everything is free</h2>
          <p>
            Every feature of Imperial Reminder - including custom reminder wording and the
            shorter waits on the listing services that offer one - is available to every
            server at no cost. There is no premium tier, no paid subscription, no purchase,
            and nothing to cancel.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>6. Availability and "as is"</h2>
          <p>
            The service is provided "as is" and "as available", without warranties of any kind.
            We do not guarantee that the bot or dashboard will be uninterrupted, error free, or
            available at any particular time, and features may change or be discontinued. In
            particular, we do not guarantee that a reminder will be delivered on time or at all -
            a missed bump is not something we can be responsible for.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>7. Limitation of liability</h2>
          <p>
            To the maximum extent permitted by law, we are not liable for any indirect,
            incidental, or consequential damages, or for any loss of data, content, or server
            ranking, arising from your use of or inability to use the bot or dashboard.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>8. Termination</h2>
          <p>
            We may suspend or revoke access to the bot or dashboard at any time, including for
            violations of these terms. Server administrators may remove the bot from their server
            at any time. You may stop using the service and remove the bot whenever you choose.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>9. Changes to these terms</h2>
          <p>
            We may update these terms from time to time. The effective date at the top of this
            page reflects the latest version. Continued use of the bot or dashboard after an
            update means you accept the revised terms.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>10. Contact</h2>
          <p>
            Questions about these terms can be sent to
            <a href="mailto:support@eosofficial.club"> support@eosofficial.club</a>.
          </p>
        </section>
      </div>
    </div>
  );
}
