import { lazy, Suspense } from "react";
import {
  Routes,
  Route,
  Navigate,
  Link,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import PageSkeleton from "./components/PageSkeleton";
import { AppFooter } from "./_engine/components/AppFooter";

/*
 * Login and the dashboard home are in the main bundle - they are where every
 * visit starts. Everything else is split out and loaded on demand, so the
 * settings forms, the legal pages and the audit table are not downloaded by
 * somebody who only ever looks at their bump timers.
 *
 * One server's overview is in the split set as well. It is a common landing
 * place, but it is reached by a click from the home page or by following a link
 * into it, and neither of those is the first paint of a cold visit.
 */
const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const SettingsHubPage = lazy(() => import("./pages/SettingsHubPage"));
const AuditLogPage = lazy(() => import("./pages/AuditLogPage"));
const PrivacyPage = lazy(() => import("./pages/PrivacyPage"));
const PrivacyPolicyPage = lazy(() => import("./pages/PrivacyPolicyPage"));
const TermsPage = lazy(() => import("./pages/TermsPage"));

export default function App() {
  return (
    <>
      <Suspense fallback={<PageSkeleton />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          {/* Public legal pages - no auth; canonical URLs for Discord review. */}
          <Route path="/privacy" element={<PrivacyPolicyPage />} />
          <Route path="/terms" element={<TermsPage />} />

          {/* Member self-service lives under /me, as it does fleet-wide. */}
          <Route path="/me" element={<MeOrRedirect />} />
          {/* The per-server landing: what the reminder is doing in this one
              server, and the server sections underneath for its managers. */}
          <Route path="/me/guilds/:guildId/overview" element={<OverviewPage />} />
          <Route path="/me/privacy" element={<PrivacyPage />} />

          {/* Admin config lives under /settings. */}
          <Route path="/settings" element={<SettingsHubPage />} />
          <Route path="/settings/guilds/:guildId/settings" element={<SettingsPage />} />
          <Route path="/settings/guilds/:guildId/audit-log" element={<AuditLogPage />} />

          {/* Back-compat. The home page was /dashboard and one server's admin
              pages were /settings/<id>, so both are out there in bookmarks and
              in Discord messages. They redirect rather than 404. */}
          <Route path="/dashboard" element={<LegacyHomeRedirect />} />
          <Route path="/settings/:guildId" element={<LegacyAdminRedirect page="settings" />} />
          <Route
            path="/settings/:guildId/audit-log"
            element={<LegacyAdminRedirect page="audit-log" />}
          />

          <Route path="*" element={<Navigate to="/me" replace />} />
        </Routes>
      </Suspense>
      <AppFooter
        brand="Empire of Shadows · Imperial Reminder Dashboard"
        extraLinks={
          <>
            <Link to="/me">Dashboard</Link>
            <a href="https://eosofficial.club" rel="noopener">
              Main Site
            </a>
          </>
        }
      />
    </>
  );
}

/**
 * What /me renders, and where an old shareable link goes.
 *
 * A single server's view used to be `?guild=<id>` on this same page, so those
 * links are out there. They now land on that server's own overview instead of
 * on a picker that no longer reads the parameter. Without the search parameter
 * this is just the dashboard home.
 */
function MeOrRedirect() {
  const [searchParams] = useSearchParams();
  const guildId = searchParams.get("guild");
  if (guildId) return <Navigate to={`/me/guilds/${guildId}/overview`} replace />;
  return <DashboardPage />;
}

/** The old home address. `?guild=` on it meant the same thing it meant on /me. */
function LegacyHomeRedirect() {
  const [searchParams] = useSearchParams();
  const guildId = searchParams.get("guild");
  return (
    <Navigate to={guildId ? `/me/guilds/${guildId}/overview` : "/me"} replace />
  );
}

/**
 * The old per-server admin addresses.
 *
 * The query string is carried over deliberately: the settings page picks its
 * open section out of `?s=`, so dropping it would turn a link to one setting
 * into a link to the top of the page.
 */
function LegacyAdminRedirect({ page }: { page: "settings" | "audit-log" }) {
  const { guildId } = useParams();
  const { search } = useLocation();
  return <Navigate to={`/settings/guilds/${guildId}/${page}${search}`} replace />;
}
