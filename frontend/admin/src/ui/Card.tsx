import type { ReactNode } from "react";

export function Card({
  title,
  action,
  children,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wide">{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
