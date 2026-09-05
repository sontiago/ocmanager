interface StatusIconProps {
  kind: "check" | "bang" | "plus" | "spinner";
}

export function StatusIcon({ kind }: StatusIconProps) {
  if (kind === "spinner") {
    return (
      <div className="size-[60px] animate-spin rounded-full border-[3px] border-divider border-t-accent" />
    );
  }
  const styles = {
    check: "bg-accent text-white text-[30px]",
    bang: "border-[3px] border-accent text-accent text-[30px]",
    plus: "bg-fill-icon text-ink text-[26px] opacity-50",
  };
  const glyphs = { check: "✓", bang: "!", plus: "+" };
  return (
    <div
      className={`grid size-[60px] place-items-center rounded-full font-extrabold ${styles[kind]}`}
    >
      {glyphs[kind]}
    </div>
  );
}
