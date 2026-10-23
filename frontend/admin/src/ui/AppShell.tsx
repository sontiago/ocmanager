import { NavLink, Outlet } from "react-router";
import { useSession } from "../api/session";
import { useT } from "../i18n";
import { buttonClass } from "./Field";

const NAV = [
  ["/", "nav.overview"],
  ["/clients", "nav.clients"],
  ["/subscriptions", "nav.subscriptions"],
  ["/plans", "nav.plans"],
  ["/payments", "nav.payments"],
  ["/devices", "nav.devices"],
  ["/node", "nav.node"],
  ["/audit", "nav.audit"],
  ["/settings", "nav.settings"],
  ["/profile", "nav.profile"],
] as const;

export function AppShell() {
  const { t, lang, setLang } = useT();
  const { admin, logout } = useSession();

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-52 shrink-0 flex-col gap-1 border-r border-border bg-surface p-3">
        <div className="mb-3 px-2 text-base font-semibold">ocmanager</div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(([to, key]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `rounded-md px-2 py-1.5 ${isActive ? "bg-accent text-accent-text" : "hover:bg-bg"}`
              }
            >
              {t(key)}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto flex flex-col gap-2 pt-4 text-sm">
          <span className="px-2 text-muted">{admin?.username}</span>
          <button
            type="button"
            className={buttonClass}
            onClick={() => setLang(lang === "ru" ? "en" : "ru")}
          >
            {lang === "ru" ? "EN" : "RU"}
          </button>
          <button type="button" className={buttonClass} onClick={() => void logout()}>
            {t("shell.logout")}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
