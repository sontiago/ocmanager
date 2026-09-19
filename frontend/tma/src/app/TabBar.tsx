import { NavLink } from "react-router";
import { IconCard, IconGrid, IconMore, IconPhone } from "../ui/icons";
import { ROUTES } from "./routes";
import { useTranslation } from "../i18n/useTranslation";
import type { MessageKey } from "../i18n/ru";

const TABS: { to: string; Icon: typeof IconCard; label: MessageKey }[] = [
  { to: ROUTES.home, Icon: IconCard, label: "nav.subscription" },
  { to: ROUTES.devices, Icon: IconPhone, label: "nav.devices" },
  { to: ROUTES.plans, Icon: IconGrid, label: "nav.plans" },
  { to: ROUTES.account, Icon: IconMore, label: "nav.more" },
];
export function TabBar() {
  const { t } = useTranslation();
  return (
    <nav className="grid shrink-0 grid-cols-4 border-t border-divider bg-surface pb-[calc(var(--safe-bottom)+8px)]">
      {TABS.map(({ to, Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === ROUTES.home}
          className={({ isActive }) =>
            `flex cursor-pointer flex-col items-center gap-[3px] px-1 pt-2 pb-1 text-[10.5px] font-semibold hover:opacity-75 ${
              isActive ? "text-accent" : "text-ink-3"
            }`
          }
        >
          <Icon size={23} />
          <span>{t(label)}</span>
        </NavLink>
      ))}
    </nav>
  );
}
