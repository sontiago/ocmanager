import { useEffect, type ReactNode } from "react";
import { useDialogFocus } from "../lib/useDialogFocus";

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose(): void;
  children: ReactNode;
}) {
  const ref = useDialogFocus<HTMLDivElement>();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-md rounded-md border-t-[3px] border-t-accent bg-surface p-5 shadow-card"
      >
        <h2 className="mb-3 text-lg font-normal">{title}</h2>
        {children}
      </div>
    </div>
  );
}
