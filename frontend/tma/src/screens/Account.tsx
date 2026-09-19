import { useState } from "react";
import { useTheme, type ThemeChoice } from "../app/ThemeProvider";
import { ACCOUNT } from "./demo";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { SectionLabel } from "../ui/SectionLabel";
import { Sheet } from "../ui/Sheet";

const T = {
  accountLabel: "АККАУНТ",
  telegramId: "Telegram ID",
  language: "Язык",
  theme: "Тема",
  support: "Поддержка",
  themeTitle: "ТЕМА",
};

const THEME_LABELS: Record<ThemeChoice, string> = {
  system: "Как в Telegram",
  light: "Светлая",
  dark: "Тёмная",
};

export function Account() {
  const { choice, setChoice } = useTheme();
  const [sheetOpen, setSheetOpen] = useState(false);

  return (
    <div>
      <SectionLabel>{T.accountLabel}</SectionLabel>
      <Card>
        {/* Идентификатор печатается без разрядных пробелов (решение C7.8):
            разряды мешают сверить его и скопировать целиком. */}
        <Cell title={T.telegramId} value={String(ACCOUNT.telegram_id)} />

        {/* Язык — факт без действия и БЕЗ шеврона (решение C4):
            он берётся из Telegram, переключателя нет. Шеврон обещал бы
            продолжение, которого не будет. */}
        <Cell title={T.language} value="Русский" />

        <Cell
          title={T.theme}
          value={THEME_LABELS[choice]}
          chevron
          onClick={() => setSheetOpen(true)}
        />
        <Cell title={T.support} value={ACCOUNT.support} />
      </Card>

      <Sheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        title={T.themeTitle}
      >
        {(Object.keys(THEME_LABELS) as ThemeChoice[]).map((option) => (
          <Cell
            key={option}
            title={THEME_LABELS[option]}
            value={
              choice === option ? (
                <span className="text-accent">✓</span>
              ) : undefined
            }
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
