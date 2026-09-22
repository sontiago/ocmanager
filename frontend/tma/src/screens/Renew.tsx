import { useNavigate } from "react-router";
import { useSubscription } from "../api/hooks";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { formatDate, formatMoney } from "../lib/format";
import { isLive, statusMessageKey } from "../lib/subscription";
import { Button } from "../ui/Button";
import { Caption } from "../ui/Caption";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { Hero } from "../ui/Hero";
import { Note } from "../ui/Note";
import { Skeleton } from "../ui/Skeleton";
import { StatusIcon } from "../ui/StatusIcon";

export function Renew() {
  const navigate = useNavigate();
  const { t, tPlural, lang } = useTranslation();

  const subscription = useSubscription();

  if (subscription.isPending) return <RenewSkeleton />;

  if (subscription.error) {
    return (
      <ErrorState
        error={subscription.error}
        onRetry={() => void subscription.refetch()}
      />
    );
  }

  const sub = subscription.data ?? null;

  // Продлевать можно только то, что ещё живо. Мёртвую подписку не продлевают,
  // а покупают заново — и вести надо в каталог, а не в оплату старого тарифа.
  if (!sub || !isLive(sub)) {
    return (
      <EmptyState
        icon={<StatusIcon kind={sub ? "bang" : "plus"} />}
        title={sub ? t(statusMessageKey(sub)) : t("subscription.none")}
        body={t("subscription.noneBody")}
        action={
          <Button onClick={() => navigate(ROUTES.plans)}>
            {sub ? t("subscription.renew") : t("subscription.choosePlan")}
          </Button>
        }
      />
    );
  }

  const days = tPlural("unit.day", sub.plan.duration_days);
  const date = sub.expires_at ? formatDate(sub.expires_at, lang) : null;

  // При живом автопродлении дата — это день списания; при выключенном та же
  // дата означает конец доступа. Одно число, два разных смысла.
  const subtitle = sub.auto_renew
    ? date === null
      ? "Tribute"
      : `${date} · Tribute`
    : date === null
      ? ""
      : t("renew.accessEnds", { date });

  return (
    <div>
      <div className="px-1 pt-3.5">
        <Caption>
          {sub.auto_renew ? t("renew.nextCharge") : t("renew.price")}
        </Caption>
        <Hero size="md">
          {formatMoney(sub.plan.price_amount, sub.plan.currency, lang)}
        </Hero>
        <Note>{subtitle}</Note>
      </div>

      <Card className="mt-5">
        {/* Некликабельная строка: рекуррентным платежом распоряжается Tribute,
            и кнопка здесь обещала бы то, чего приложение не умеет. */}
        <Cell
          title={t("subscription.autoRenew")}
          subtitle={t("renew.managed")}
          value={t(sub.auto_renew ? "subscription.on" : "subscription.off")}
        />
        <Cell title={t("checkout.plan")} value={sub.plan.name} />
        <Cell title={t("checkout.period")} value={days} />
      </Card>

      <Note className="px-1 pt-3.5">{t("renew.note")}</Note>

      <Button
        className="mt-[18px]"
        onClick={() => navigate(ROUTES.checkout(sub.plan.code))}
      >
        {t("renew.submit", { days })}
      </Button>
    </div>
  );
}

function RenewSkeleton() {
  return (
    <div className="space-y-3 pt-4">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-12 w-1/2" />
      <Skeleton className="h-40 w-full rounded-card" />
      <Skeleton className="h-14 w-full rounded-btn" />
    </div>
  );
}
