import type { Lang } from "../telegram/auth";

export type PluralForm = "one" | "few" | "many" | "other";

const rules: Record<Lang, Intl.PluralRules> = {
  ru: new Intl.PluralRules("ru-RU"),
  en: new Intl.PluralRules("en-US"),
};

export function pluralForm(lang: Lang, count: number): PluralForm {
  const form = rules[lang].select(count);
  // 'zero' и 'two' в ru/en не встречаются, но тип Intl их допускает.
  return form === "zero" || form === "two" ? "other" : (form as PluralForm);
}
