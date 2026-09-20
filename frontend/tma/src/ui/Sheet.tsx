import { useEffect, type ReactNode } from "react";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export function Sheet({ open, onClose, title, children }: SheetProps) {
  // Escape — обязательный выход: внутри Telegram лист перекрывает экран целиком,
  // и без клавиатурного закрытия он становится ловушкой для скринридера.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

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
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative rounded-t-card bg-surface pb-[calc(var(--safe-bottom)+12px)]"
      >
        <div className="px-5 pt-4 pb-1 text-[11.5px] tracking-[0.02em] text-ink-3">
          {title}
        </div>
        {children}
      </div>
    </div>
  );
}
