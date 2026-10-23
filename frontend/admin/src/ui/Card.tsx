import type { ReactNode } from "react";

/** Карточка AdminLTE: цветная полоса сверху, заголовок с линией под ним. */
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
    <section
      aria-label={typeof title === "string" ? title : undefined}
      className="rounded-md border-t-[3px] border-t-accent bg-surface shadow-card"
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 className="text-lg font-normal">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}
