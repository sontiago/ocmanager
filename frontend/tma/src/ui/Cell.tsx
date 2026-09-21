import type { ReactNode } from "react";
import { haptic } from "../telegram/haptics";

interface CellProps {
  icon?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  value?: ReactNode;
  chevron?: boolean;
  onClick?: () => void;
  /** «start» — для многострочных пунктов инструкции. */
  align?: "center" | "start";
  /** Подсветка строки: текущий тариф в списке. */
  highlighted?: boolean;
  className?: string;
  /** Необратимое действие строкой списка: «Отозвать устройство». */
  destructive?: boolean;
}

export function Cell({
  icon,
  title,
  subtitle,
  value,
  chevron,
  onClick,
  align = "center",
  highlighted = false,
  className = "",
  destructive = false,
}: CellProps) {
  const base = [
    // класс cell — зацепка для правила .cell + .cell в index.css
    "cell flex w-full gap-[13px] px-4 py-3.5 text-left",
    align === "start" ? "items-start" : "items-center",
    highlighted ? "bg-accent-tint-weak" : "",
    className,
  ].join(" ");

  const body = (
    <>
      {icon}
      <span className="flex min-w-0 flex-1 flex-col">
        <span
          className={`text-[15px] font-semibold leading-tight ${
            destructive ? "text-danger" : ""
          }`}
        >
          {title}
        </span>
        {subtitle && (
          <span className="mt-0.5 text-[12.5px] leading-[1.35] text-ink-2">
            {subtitle}
          </span>
        )}
      </span>
      {value && (
        <span className="shrink-0 text-sm font-extrabold">{value}</span>
      )}
      {chevron && (
        <span className="shrink-0 text-[17px] leading-none text-ink-4">›</span>
      )}
    </>
  );

  if (!onClick) return <div className={base}>{body}</div>;

  return (
    <button
      type="button"
      onClick={() => {
        haptic.selection();
        onClick();
      }}
      className={`${base} cursor-pointer hover:bg-row-hover active:bg-row-press`}
    >
      {body}
    </button>
  );
}
