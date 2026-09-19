import { createContext, useMemo, useState, type ReactNode } from "react";
import { getTelegramLang, type Lang } from "../telegram/auth";
import { en, enPlural } from "./en";
import { ru, ruPlural } from "./ru";
import type { MessageKey, PluralKey } from "./ru";
import { pluralForm } from "./plural";

export interface I18nApi {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
  tPlural: (
    key: PluralKey,
    count: number,
    params?: Record<string, string | number>,
  ) => string;
}

export const I18nContext = createContext<I18nApi | null>(null);

const catalogs = { ru, en } as const;
const plurals = { ru: ruPlural, en: enPlural } as const;

/** Заменяет `{name}` на значение; неизвестные плейсхолдеры остаются как есть. */
function interpolate(
  template: string,
  params?: Record<string, string | number>,
): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in params ? String(params[key]) : match,
  );
}

export function I18nProvider({
  lang: forced,
  children,
}: {
  lang?: Lang;
  children: ReactNode;
}) {
  const [lang, setLang] = useState<Lang>(forced ?? getTelegramLang());

  const api = useMemo<I18nApi>(
    () => ({
      lang,
      setLang,
      t: (key, params) => interpolate(catalogs[lang][key], params),
      tPlural: (key, count, params) => {
        const forms = plurals[lang][key];
        const template = forms[pluralForm(lang, count)];
        return interpolate(template, { n: count, ...params });
      },
    }),
    [lang],
  );

  return <I18nContext.Provider value={api}>{children}</I18nContext.Provider>;
}
