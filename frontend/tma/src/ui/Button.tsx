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

export function Button({
  children,
  onClick,
  variant = "primary",
  loading = false,
  disabled = false,
  type = "button",
  className = "",
}: ButtonProps) {
  const variants = {
    primary: "bg-accent text-white hover:bg-accent-600 active:bg-accent-700",
    secondary: "bg-fill text-ink hover:bg-fill-strong",
    destructive: "bg-danger-fill text-danger",
  };
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
      className={`w-full cursor-pointer rounded-btn p-4 text-center text-base font-extrabold transition-opacity disabled:cursor-default disabled:opacity-50 ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
