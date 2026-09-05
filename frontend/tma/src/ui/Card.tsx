import type { ReactNode } from "react";

/** Карточка списка. overflow-hidden обязателен: он обрезает
 *  подсветку строки по скруглённому углу. */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`overflow-hidden rounded-card bg-surface ${className}`}>
      {children}
    </div>
  );
}
