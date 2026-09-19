import type { ReactNode } from "react";

interface NoteProps {
  children: ReactNode;
  /** «lg» — крупнее, для экранов-состояний: пусто, ошибка, ожидание. */
  size?: "sm" | "lg";
  className?: string;
}

export function Note({ children, size = "sm", className = "" }: NoteProps) {
  const sizes = { sm: "text-[12.5px]", lg: "text-[13.5px]" };
  return (
    <div className={`${sizes[size]} leading-[1.35] text-ink-2 ${className}`}>
      {children}
    </div>
  );
}
