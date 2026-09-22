import { useState } from "react";
import { useMe } from "../api/hooks";
import { useTheme, type ThemeChoice } from "../app/ThemeProvider";
import { env } from "../env";
import { useTranslation } from "../i18n/useTranslation";
import type { MessageKey } from "../i18n/ru";
import type { Lang } from "../telegram/auth";
import { openInTelegram } from "../telegram/links";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { Sheet } from "../ui/Sheet";

/** Имена языков — самоназвания: одинаковы в любой локали, в каталог не идут. */
const LANG_NAME: Record<Lang, string> = { ru: "Русский", en: "English" };

const THEME_KEYS: Record<ThemeChoice, MessageKey> = {
  system: "account.themeSystem",
  light: "account.themeLight",
  dark: "account.themeDark",
};

const THEME_ORDER: ThemeChoice[] = ["system", "light", "dark"];

export function Account() {
  const { t, lang } = useTranslation();
  const { choice, setChoice } = useTheme();
  const me = useMe();

  const [sheetOpen, setSheetOpen] = useState(false);

  const supportUrl = `https://t.me/${env.supportHandle.replace(/^@/, "")}`;

  return (
    <div className="pt-3.5">
      <Card>
        {/* Идентификатор печатается без разрядных пробелов (C7.8): разряды
            мешают сверить его глазами и скопировать целиком.
            Строки нет, пока не пришёл ответ, — экран из-за этого не ждёт. */}
        {me.data && (
          <Cell title="Telegram ID" value={String(me.data.telegram_id)} />
        )}

        {/* Язык — факт без действия и БЕЗ шеврона (C4): он приходит из
            Telegram, переключателя нет. Шеврон обещал бы продолжение. */}
        <Cell title={t("account.language")} value={LANG_NAME[lang]} />

        <Cell
          title={t("account.theme")}
          value={t(THEME_KEYS[choice])}
          chevron
          onClick={() => setSheetOpen(true)}
        />

        <Cell
          title={t("account.support")}
          value={env.supportHandle}
          chevron
          onClick={() => openInTelegram(supportUrl)}
        />
      </Card>

      <Sheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        title={t("account.theme")}
      >
        {THEME_ORDER.map((option) => (
          <Cell
            key={option}
            title={t(THEME_KEYS[option])}
            selected={choice === option}
            onClick={() => {
              setChoice(option);
              setSheetOpen(false);
            }}
          />
        ))}
      </Sheet>
    </div>
  );
}
