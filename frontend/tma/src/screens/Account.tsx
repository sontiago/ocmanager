import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useMe, useReferral, useRedeemPromo } from "../api/hooks";
import type { PromoResult } from "../api/types";
import { ROUTES } from "../app/routes";
import { useTheme, type ThemeChoice } from "../app/ThemeProvider";
import { env } from "../env";
import { useTranslation } from "../i18n/useTranslation";
import { formatBytes } from "../lib/format";
import type { MessageKey } from "../i18n/ru";
import type { Lang } from "../telegram/auth";
import { openInTelegram } from "../telegram/links";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { Note } from "../ui/Note";
import { Sheet } from "../ui/Sheet";

/** Имена языков — самоназвания: одинаковы в любой локали, в каталог не идут. */
const LANG_NAME: Record<Lang, string> = { ru: "Русский", en: "English" };

const THEME_KEYS: Record<ThemeChoice, MessageKey> = {
  system: "account.themeSystem",
  light: "account.themeLight",
  dark: "account.themeDark",
};

const THEME_ORDER: ThemeChoice[] = ["system", "light", "dark"];

/** Лист ввода промокода: награда или причина отказа показываются тут же, лист не закрывается. */
function PromoSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, lang } = useTranslation();
  const redeem = useRedeemPromo();
  const [code, setCode] = useState("");
  const [done, setDone] = useState<PromoResult | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    setDone(null);
    redeem.mutate(code.trim(), {
      onSuccess: (result) => {
        setDone(result);
        setCode("");
      },
    });
  }

  return (
    <Sheet open={open} onClose={onClose} title={t("promo.title")}>
      <form onSubmit={submit} className="space-y-3 px-5 pt-2 pb-3">
        <input
          aria-label={t("promo.label")}
          value={code}
          placeholder={t("promo.placeholder")}
          autoCapitalize="characters"
          autoComplete="off"
          maxLength={64}
          onChange={(e) => {
            setCode(e.target.value);
            setDone(null);
            redeem.reset();
          }}
          className="w-full rounded-btn bg-fill p-3.5 text-[15px] outline-none"
        />
        {redeem.error && (
          <Note tone="danger" size="lg">
            {t(redeem.error.messageKey())}
          </Note>
        )}
        {done && (
          <Note size="lg">
            {done.kind === "days"
              ? t("promo.doneDays", { days: done.value })
              : t("promo.doneTraffic", { traffic: formatBytes(done.value, lang) })}
          </Note>
        )}
        <Button type="submit" loading={redeem.isPending} disabled={code.trim() === ""}>
          {t("promo.apply")}
        </Button>
      </form>
    </Sheet>
  );
}

export function Account() {
  const { t, lang } = useTranslation();
  const navigate = useNavigate();
  const { choice, setChoice } = useTheme();
  const me = useMe();
  // Значки — украшение: не загрузились, строки просто нет, аккаунт не ждёт и не падает.
  const referral = useReferral();
  const badges = referral.data?.badges ?? [];

  const [sheetOpen, setSheetOpen] = useState(false);
  const [promoOpen, setPromoOpen] = useState(false);

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

        {badges.length > 0 && (
          <Cell
            title={t("account.badges")}
            value={badges.map((b) => t(`badge.${b}`)).join(" · ")}
          />
        )}

        <Cell
          title={t("account.friends")}
          chevron
          onClick={() => void navigate(ROUTES.friends)}
        />

        <Cell title={t("account.promo")} chevron onClick={() => setPromoOpen(true)} />

        <Cell
          title={t("account.support")}
          value={env.supportHandle}
          chevron
          onClick={() => openInTelegram(supportUrl)}
        />
      </Card>

      <PromoSheet open={promoOpen} onClose={() => setPromoOpen(false)} />

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
