export function ProgressBar({ percent }: { percent: number }) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      className="mt-2.5 h-2 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--c-text)_9%,transparent)]"
    >
      <div className="h-full bg-accent" style={{ width: `${clamped}%` }} />
    </div>
  );
}
