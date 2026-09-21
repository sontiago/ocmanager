import type { ReactNode } from "react";

interface NoteProps {
  children: ReactNode;
  /** «lg» — крупнее, для экранов-состояний: пусто, ошибка, ожидание. */
  size?: "sm" | "lg";
  /** «danger» — причина неудавшегося действия внутри карточки. */
  tone?: "muted" | "danger";
  className?: string;
}

const SIZES = { sm: "text-[12.5px]", lg: "text-[13.5px]" };
const TONES = { muted: "text-ink-2", danger: "text-danger" };

export function Note({
  children,
  size = "sm",
  tone = "muted",
  className = "",
}: NoteProps) {
  return (
    <div
      className={`${SIZES[size]} leading-[1.35] ${TONES[tone]} ${className}`}
    >
      {children}
    </div>
  );
}
