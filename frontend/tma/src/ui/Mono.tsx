import type { ReactNode } from "react";

/** Моноширинное значение: код ошибки, имя вебхука. */
export function Mono({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <code className={`font-mono text-[12.5px] ${className}`}>{children}</code>
  );
}
