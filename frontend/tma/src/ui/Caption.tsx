import type { ReactNode } from "react";

/** Мелкая подпись над цифрой-героем: «Доступ активен ещё», «К оплате». */
export function Caption({ children }: { children: ReactNode }) {
  return <div className="text-[12.5px] text-ink-2">{children}</div>;
}
