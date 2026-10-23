export type Tone = "ok" | "warn" | "danger" | "neutral";

const TONES: Record<Tone, string> = {
  ok: "text-ok border-ok",
  warn: "text-warn border-warn",
  danger: "text-danger border-danger",
  neutral: "text-muted border-border",
};

export function StatusBadge({ tone = "neutral", label }: { tone?: Tone; label: string }) {
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${TONES[tone]}`}>
      {label}
    </span>
  );
}
