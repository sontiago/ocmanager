/** Заглушка на время загрузки: высота и ширина задаются классами снаружи. */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse rounded-lg bg-fill ${className}`}
    />
  );
}
