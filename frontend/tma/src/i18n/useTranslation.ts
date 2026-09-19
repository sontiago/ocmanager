import { useContext } from "react";
import { I18nContext, type I18nApi } from "./I18nProvider";

export function useTranslation(): I18nApi {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useTranslation вызван вне <I18nProvider>");
  return ctx;
}
