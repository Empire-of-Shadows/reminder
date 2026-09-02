import { NavLink } from "react-router-dom";

function navClass({ isActive }: { isActive: boolean }) {
  return "nav-button" + (isActive ? " active" : "");
}

/** The admin tab bar for one server's management pages, so the admin tree
 *  navigates within itself instead of dropping back into the member view.
 *
 *  Both tabs are always shown. Hiding a link was never the gate - the server
 *  re-checks the panel tier on every read and every write, so a link somebody
 *  should not have leads to a refusal rather than to data.
 *
 *  "Change history" is what this bot calls the audit log everywhere a person can
 *  read it, so the tab says the same thing rather than introducing a second name
 *  for one page. */
export default function AdminNav({ guildId }: { guildId: string }) {
  return (
    <nav className="nav-links" style={{ marginBottom: 20 }}>
      <NavLink to="/settings" end className="nav-button">&larr; Your servers</NavLink>
      <NavLink to={`/settings/guilds/${guildId}/settings`} className={navClass}>
        Settings
      </NavLink>
      <NavLink to={`/settings/guilds/${guildId}/audit-log`} className={navClass}>
        Change history
      </NavLink>
    </nav>
  );
}
