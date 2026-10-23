import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { setFormatLang } from "../lib/format";
import en from "./en.json";
import ru from "./ru.json";

export type Lang = "ru" | "en";
export type Dictionary = Record<string, string>;
type Vars = Record<string, string | number>;

const DEFAULTS: Record<Lang, Dictionary> = { ru, en };
const STORAGE_KEY = "ocm_lang";

interface I18n {
  lang: Lang;
  setLang(lang: Lang): void;
  t(key: string, vars?: Vars): string;
}

function translate(dict: Dictionary, key: string, vars?: Vars): string {
  const template = dict[key] ?? key;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (m, name: string) =>
    name in vars ? String(vars[name]) : m,
  );
}

const fallback: I18n = {
  lang: "ru",
  setLang: () => {},
  t: (key, vars) => translate(ru, key, vars),
};

const I18nContext = createContext<I18n>(fallback);

function storedLang(): Lang {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "en" ? "en" : "ru";
  } catch {
    return "ru";
  }
}

export function I18nProvider({
  children,
  dictionaries = DEFAULTS,
}: {
  children: ReactNode;
  dictionaries?: Record<Lang, Dictionary>;
}) {
  const [lang, setLangState] = useState<Lang>(storedLang);
  setFormatLang(lang);

  const setLang = useCallback((next: Lang) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // приватный режим: язык не запоминается, интерфейс работает
    }
    setLangState(next);
  }, []);

  const value = useMemo<I18n>(
    () => ({ lang, setLang, t: (key, vars) => translate(dictionaries[lang], key, vars) }),
    [lang, setLang, dictionaries],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT(): I18n {
  return useContext(I18nContext);
}
