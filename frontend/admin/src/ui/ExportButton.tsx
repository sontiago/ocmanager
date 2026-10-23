import { useT } from "../i18n";
import { queryString, type Query } from "../api/client";
import { buttonClass } from "./Field";

export type ExportKind = "clients" | "subscriptions" | "payments" | "audit" | "traffic";

/** Адрес выгрузки с теми же фильтрами, что у списка. Пустые значения в адрес не попадают. */
export function exportUrl(kind: ExportKind, params: Query): string {
  const clean: Query = {};
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") clean[key] = value;
  }
  return `/admin/export/${kind}.csv${queryString(clean)}`;
}

/** Обычная ссылка со скачиванием: GET несёт cookie сессии, CSRF для него не нужен. */
export function ExportButton({ kind, params }: { kind: ExportKind; params: Query }) {
  const { t } = useT();
  return (
    <a className={`${buttonClass} inline-block`} href={exportUrl(kind, params)} download>
      {t("export.csv")}
    </a>
  );
}
