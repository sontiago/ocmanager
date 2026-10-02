export function Header({
  title,
  onBack,
  backLabel,
}: {
  title: string;
  /** Есть экран выше — рисуем собственную кнопку «Назад» (родная кнопка Telegram есть не везде). */
  onBack?: () => void;
  backLabel?: string;
}) {
  return (
    <div className="flex shrink-0 items-center gap-2 px-3.5 pt-[calc(var(--safe-top)+8px)] pb-2.5">
      {onBack && (
        <button
          type="button"
          aria-label={backLabel}
          onClick={onBack}
          className="-ml-1 flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-full bg-fill text-ink active:bg-fill-strong"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M15 5l-7 7 7 7" />
          </svg>
        </button>
      )}
      <h1 className="flex-1 text-[17px] font-extrabold leading-tight tracking-[-0.01em]">
        {title}
      </h1>
    </div>
  );
}
