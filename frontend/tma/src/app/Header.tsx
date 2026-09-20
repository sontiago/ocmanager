export function Header({ title }: { title: string }) {
  return (
    <div className="flex shrink-0 items-center px-3.5 pt-[calc(var(--safe-top)+8px)] pb-2.5">
      <h1 className="flex-1 text-[17px] font-extrabold leading-tight tracking-[-0.01em]">
        {title}
      </h1>
    </div>
  );
}
