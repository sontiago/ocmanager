import type { ReactNode } from "react";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export function Sheet({ open, onClose, title, children }: SheetProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      {/* Затемнение — отдельный слой: клик по нему закрывает лист,
          клик по самому листу не должен всплывать до него. */}
      <button
        type="button"
        aria-label="Закрыть"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-black/40"
      />
      <div className="relative rounded-t-card bg-surface pb-[calc(var(--safe-bottom)+12px)]">
        <div className="px-5 pt-4 pb-1 text-[11.5px] tracking-[0.02em] text-ink-3">
          {title}
        </div>
        {children}
      </div>
    </div>
  );
}
