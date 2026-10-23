import { useEffect, type ReactNode } from "react";
import { useT } from "../i18n";
import { buttonClass, dangerButtonClass, primaryButtonClass } from "./Field";

interface Props {
  open: boolean;
  title: string;
  body?: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  pending?: boolean;
  onConfirm(): void;
  onCancel(): void;
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  danger,
  pending,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useT();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-md rounded-md border-t-[3px] border-t-accent bg-surface p-5 shadow-card"
      >
        <h2 className="mb-2 text-lg font-normal">{title}</h2>
        {body && <div className="mb-4 text-sm text-muted">{body}</div>}
        <div className="flex justify-end gap-2">
          <button type="button" className={buttonClass} onClick={onCancel} disabled={pending}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className={danger ? dangerButtonClass : primaryButtonClass}
            onClick={onConfirm}
            disabled={pending}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
