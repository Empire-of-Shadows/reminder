import { NavLink } from "react-router-dom";
import type { PanelRole } from "../api/types";

function navClass({ isActive }: { isActive: boolean }) {
  return "nav-button" + (isActive ? " active" : "");
}

/** Per-guild tab bar: Overview (every member) + Settings (admins). The admin
 *  link is HIDDEN here, not enforced here - every admin route re-checks the
 *  tier server-side.
 *
 *  Imperial Reminder gives a member exactly one page per server, so Overview is
 *  the only member tab there is. The bar is still worth rendering: it is what
 *  says which server you are looking at the pages of, and it is the way back to
 *  the picker without reaching for the browser's back button.
 *
 *  A server the bot is not in yet (`setupRequired`) keeps only the back link and
 *  Overview: the other tabs would lead to pages with nothing behind them, and a
 *  row of dead ends next to an invite card reads as broken rather than empty. */
export default function GuildNav({
  guildId,
  panelRole,
  setupRequired = false,
}: {
  guildId: string;
  panelRole?: PanelRole;
  setupRequired?: boolean;
}) {
  const canSeeSettings = panelRole === "admin" && !setupRequired;
  return (
    <nav className="nav-links" style={{ marginBottom: 20 }}>
      <NavLink to="/me" end className="nav-button">&larr; Servers</NavLink>
      <NavLink to={`/me/guilds/${guildId}/overview`} className={navClass}>Overview</NavLink>
      {canSeeSettings && (
        <NavLink to={`/settings/guilds/${guildId}/settings`} className={navClass}>
          Settings
        </NavLink>
      )}
    </nav>
  );
}
