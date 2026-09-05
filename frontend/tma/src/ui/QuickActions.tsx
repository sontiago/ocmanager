import type { ReactNode } from "react";

export interface QuickAction {
  icon: ReactNode;
  label: string;
  onClick: () => void;
}

export function QuickActions({ items }: { items: QuickAction[] }) {
  return (
    <div className="mt-[18px] flex gap-2">
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          onClick={item.onClick}
          className="group flex flex-1 cursor-pointer flex-col items-center gap-2"
        >
          <span className="grid size-14 place-items-center rounded-full bg-surface text-accent group-hover:bg-[color-mix(in_srgb,var(--c-accent)_12%,transparent)]">
            {item.icon}
          </span>
          <span className="text-center text-[11.5px] leading-tight text-ink-2">
            {item.label}
          </span>
        </button>
      ))}
    </div>
  );
}
