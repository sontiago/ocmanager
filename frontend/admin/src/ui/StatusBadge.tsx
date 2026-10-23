export type Tone = "ok" | "warn" | "danger" | "neutral";

const TONES: Record<Tone, string> = {
  ok: "bg-ok text-white",
  warn: "bg-[#ffc107] text-[#1f2d3d]",
  danger: "bg-danger text-white",
  neutral: "bg-[#6c757d] text-white",
};

export function StatusBadge({ tone = "neutral", label }: { tone?: Tone; label: string }) {
  return (
    <span className={`inline-block rounded-sm px-1.5 py-0.5 text-xs font-bold ${TONES[tone]}`}>
      {label}
    </span>
  );
}
