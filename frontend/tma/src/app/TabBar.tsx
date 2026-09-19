import { NavLink } from "react-router";
import { IconCard, IconGrid, IconMore, IconPhone } from "../ui/icons";
import { ROUTES } from "./routes";

const TABS = [
  { to: ROUTES.home, Icon: IconCard, label: "Подписка" },
  { to: ROUTES.devices, Icon: IconPhone, label: "Устройства" },
  { to: ROUTES.plans, Icon: IconGrid, label: "Тарифы" },
  { to: ROUTES.account, Icon: IconMore, label: "Ещё" },
];

export function TabBar() {
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
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
