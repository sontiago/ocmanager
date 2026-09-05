import type { ReactNode } from "react";

/** Заголовок секции капсом над карточкой. */
export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="px-1 pt-4 pb-1.5 text-[11.5px] tracking-[0.02em] text-ink-3">
      {children}
    </div>
  );
}
