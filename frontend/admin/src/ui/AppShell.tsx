import { NavLink, Outlet } from "react-router";
import { useSession } from "../api/session";
import { useT } from "../i18n";
import { buttonClass } from "./Field";
import { Icon, type IconName } from "./Icon";

const NAV: readonly (readonly [string, string, IconName])[] = [
  ["/", "nav.overview", "home"],
  ["/stats", "nav.stats", "activity"],
  ["/clients", "nav.clients", "users"],
  ["/subscriptions", "nav.subscriptions", "refresh"],
  ["/plans", "nav.plans", "tag"],
  ["/payments", "nav.payments", "card"],
  ["/devices", "nav.devices", "phone"],
  ["/node", "nav.node", "server"],
  ["/audit", "nav.audit", "list"],
  ["/settings", "nav.settings", "sliders"],
  ["/profile", "nav.profile", "user"],
];

/** Каркас в духе AdminLTE: тёмный сайдбар слева, белая верхняя панель, светлое поле контента. */
export function AppShell() {
  const { t, lang, setLang } = useT();
  const { admin, logout } = useSession();

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col bg-sidebar text-sidebar-text">
        <div className="border-b border-sidebar-border px-4 py-3 text-xl font-light text-white">
          <b>ocm</b>anager
        </div>
        <nav className="flex flex-col gap-0.5 p-2">
          {NAV.map(([to, key, icon]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-3 py-2 ${isActive ? "bg-accent text-white" : "hover:bg-white/10 hover:text-white"}`
              }
            >
              <Icon name={icon} />
              {t(key)}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end gap-3 border-b border-border bg-surface px-6 py-2 shadow-card">
          <span className="text-muted">{admin?.username}</span>
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
        </header>
        <main className="min-w-0 flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
