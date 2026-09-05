import type { ReactNode } from "react";

interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary";
  className?: string;
}

export function Button({
  children,
  onClick,
  variant = "primary",
  className = "",
}: ButtonProps) {
  const variants = {
    primary: "bg-accent text-white hover:bg-accent-600 active:bg-accent-700",
    secondary: "bg-fill text-ink hover:bg-fill-strong",
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full cursor-pointer rounded-btn p-4 text-center text-base font-extrabold ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
