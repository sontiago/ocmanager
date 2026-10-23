import type { ReactNode } from "react";

export function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      {children}
      {error && (
        <span role="alert" className="mt-1 block text-danger">
          {error}
        </span>
      )}
    </label>
  );
}

export const inputClass =
  "w-full rounded-md border border-border bg-surface px-3 py-1.5 text-text outline-none focus:border-accent focus:shadow-[0_0_0_0.2rem_rgba(0,123,255,0.25)] disabled:opacity-60";
export const buttonClass =
  "rounded-md border border-border bg-[#f8f9fa] px-3 py-1.5 text-[#212529] hover:bg-[#e2e6ea] disabled:opacity-50 disabled:cursor-not-allowed dark:bg-[#6c757d]";
export const primaryButtonClass =
  "rounded-md border border-accent bg-accent px-3 py-1.5 text-accent-text hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed";
export const dangerButtonClass =
  "rounded-md border border-danger bg-danger px-3 py-1.5 text-white hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed";
