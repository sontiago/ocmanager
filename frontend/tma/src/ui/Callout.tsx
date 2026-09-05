import type { ReactNode } from "react";

/** Плашка, подсвеченная акцентом: пробный период, срок жизни ссылки. */
export function Callout({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`mt-3 rounded-card bg-accent-tint p-4 ${className}`}>
      {children}
    </div>
  );
}
