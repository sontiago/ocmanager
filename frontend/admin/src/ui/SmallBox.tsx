import type { ReactNode } from "react";
import { Link } from "react-router";
import { Icon, type IconName } from "./Icon";

type Color = "info" | "ok" | "warn" | "danger" | "accent";

const COLORS: Record<Color, string> = {
  info: "bg-info text-white",
  ok: "bg-ok text-white",
  warn: "bg-[#ffc107] text-[#1f2d3d]",
  danger: "bg-danger text-white",
  accent: "bg-accent text-accent-text",
};

/** Цветной виджет AdminLTE: крупное число, подпись, необязательная ссылка «подробнее». */
export function SmallBox({
  color,
  value,
  label,
  icon,
  to,
  moreLabel,
}: {
  color: Color;
  value: ReactNode;
  label: string;
  icon?: IconName;
  to?: string;
  moreLabel?: string;
}) {
  const body = (
    <div className="relative px-4 pt-3 pb-3">
      {icon && <Icon name={icon} size={56} className="absolute top-3 right-4 opacity-15" />}
      <div className="text-2xl font-bold leading-tight">{value}</div>
      <div className="text-sm">{label}</div>
    </div>
  );
  return (
    <div className={`overflow-hidden rounded-md shadow-card ${COLORS[color]}`}>
      {to ? (
        <Link to={to} className="block hover:opacity-90">
          {body}
          {moreLabel && (
            <div className="bg-black/10 px-4 py-1 text-center text-sm">{moreLabel} →</div>
          )}
        </Link>
      ) : (
        body
      )}
    </div>
  );
}
