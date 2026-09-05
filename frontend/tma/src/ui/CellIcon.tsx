import type { ReactNode } from "react";

interface CellIconProps {
  children: ReactNode;
  /** accent — синий круг (по умолчанию), neutral — серый, solid — заливка акцентом. */
  tone?: "accent" | "neutral" | "solid";
  /** Мелкий текст для трёхбуквенных бейджей: mac, and, win. */
  small?: boolean;
}

export function CellIcon({ children, tone = "accent", small }: CellIconProps) {
  const tones = {
    accent: "bg-accent-fill text-accent-700",
    neutral: "bg-fill-icon text-ink",
    solid: "bg-accent text-white",
  };
  return (
    <span
      className={`grid size-10 shrink-0 place-items-center rounded-full font-extrabold ${
        small ? "text-[11px]" : "text-sm"
      } ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
