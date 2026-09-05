import type { ReactNode } from "react";

/** Маленький бейдж внутри заголовка строки: «ТЕКУЩИЙ». */
export function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="ml-1 rounded-full bg-accent px-2 py-0.5 align-[1px] text-[10px] font-extrabold tracking-[0.06em] text-white">
      {children}
    </span>
  );
}
