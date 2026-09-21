import type { ReactNode } from "react";

type Tone = "accent" | "success" | "warning" | "danger" | "neutral";

const TONES: Record<Tone, string> = {
  accent: "bg-accent text-white",
  success: "bg-success text-white",
  warning: "bg-warning text-white",
  danger: "bg-danger text-white",
  neutral: "bg-fill-icon text-ink-2",
};

/** Маленький бейдж внутри заголовка строки: «ТЕКУЩИЙ», «ИСТЕКЛА». */
export function Badge({
  children,
  tone = "accent",
}: {
  children: ReactNode;
  tone?: Tone;
}) {
  return (
    <span
      className={`ml-1 rounded-full px-2 py-0.5 align-[1px] text-[10px] font-extrabold tracking-[0.06em] ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
