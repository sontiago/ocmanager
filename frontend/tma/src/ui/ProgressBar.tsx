type Tone = "normal" | "warning" | "danger";

const FILLS: Record<Tone, string> = {
  normal: "bg-accent",
  warning: "bg-warning",
  danger: "bg-danger",
};

export function ProgressBar({
  percent,
  tone = "normal",
}: {
  percent: number;
  tone?: Tone;
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      className="mt-2.5 h-2 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--c-text)_9%,transparent)]"
    >
      <div
        className={`h-full ${FILLS[tone]}`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
