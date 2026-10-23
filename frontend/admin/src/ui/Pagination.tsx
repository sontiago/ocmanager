import { useT } from "../i18n";
import { buttonClass } from "./Field";

interface Props {
  total: number;
  limit: number;
  offset: number;
  onChange(offset: number): void;
}

export function Pagination({ total, limit, offset, onChange }: Props) {
  const { t } = useT();
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="flex items-center justify-end gap-3 py-2 text-sm text-muted">
      <span>{t("common.range", { from, to, total })}</span>
      <button
        type="button"
        className={buttonClass}
        disabled={offset <= 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        {t("common.prev")}
      </button>
      <button
        type="button"
        className={buttonClass}
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        {t("common.next")}
      </button>
    </div>
  );
}
