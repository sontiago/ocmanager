import type { ReactNode } from "react";
import { haptic } from "../telegram/haptics";

interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "destructive";
  /** Операция в процессе: кнопка заблокирована и помечена для скринридера. */
  loading?: boolean;
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}

const VARIANTS = {
  primary: "bg-accent text-white hover:bg-accent-600 active:bg-accent-700",
  secondary: "bg-fill text-ink hover:bg-fill-strong",
  destructive: "bg-danger-fill text-danger",
};

const BASE =
  "block w-full cursor-pointer rounded-btn p-4 text-center text-base font-extrabold transition-opacity";

interface ButtonLinkProps {
  children: ReactNode;
  href: string;
  variant?: "primary" | "secondary";
  className?: string;
}

/**
 * Кнопка-ссылка: обычный `<a target="_blank">`. Нажатие по ссылке клиент Telegram обрабатывает
 * сам и надёжно, в отличие от openLink из кода, который на части клиентов молча не срабатывает.
 * Годится там, где адрес известен заранее (файл ключа, магазин приложений).
 */
export function ButtonLink({
  children,
  href,
  variant = "primary",
  className = "",
}: ButtonLinkProps) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={() => haptic.impact("light")}
      className={`${BASE} ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </a>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  loading = false,
  disabled = false,
  type = "button",
  className = "",
}: ButtonProps) {
  const inactive = disabled || loading;

  return (
    <button
      type={type}
      disabled={inactive}
      aria-busy={loading || undefined}
      onClick={() => {
        if (inactive) return;
        haptic.impact("light");
        onClick?.();
      }}
      className={`${BASE} disabled:cursor-default disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
