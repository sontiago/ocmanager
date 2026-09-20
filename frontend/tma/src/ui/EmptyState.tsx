import type { ReactNode } from "react";
import { Note } from "./Note";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  body?: string;
  /** Кнопка или ссылка — собирает экран, здесь только место под неё. */
  action?: ReactNode;
}

export function EmptyState({ icon, title, body, action }: EmptyStateProps) {
  return (
    <div className="px-1 pt-[26px]">
      {icon}
      <div className="mt-5 mb-2 text-[22px] font-extrabold leading-[1.15] tracking-[-0.02em]">
        {title}
      </div>
      {body && <Note size="lg">{body}</Note>}
      {action && <div className="mt-[18px]">{action}</div>}
    </div>
  );
}
