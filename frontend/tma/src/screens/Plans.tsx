import { useNavigate } from "react-router";
import { useMe, usePlans, useStartTrial, useSubscription } from "../api/hooks";
import type { Plan } from "../api/types";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { formatBytes, formatMoney } from "../lib/format";
import { isLive } from "../lib/subscription";
import { TRIAL_PREVIEW } from "../lib/trial";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { ErrorState } from "../ui/ErrorState";
import { Note } from "../ui/Note";
import { SectionLabel } from "../ui/SectionLabel";
import { Skeleton } from "../ui/Skeleton";

export function Plans() {
  const navigate = useNavigate();
  const { t, tPlural, lang } = useTranslation();

  const plans = usePlans();
  const me = useMe();
  const subscription = useSubscription();
  const startTrial = useStartTrial();

  // Экран стоит на трёх запросах. Пока не пришли все три, неизвестно ни какой
  // тариф текущий, ни доступен ли trial: показать каталог раньше — значит
  // перерисовать его через мгновение уже с пометками. Скелет честнее.
  if (plans.isPending || me.isPending || subscription.isPending) {
    return <PlansSkeleton />;
  }

  const retryAll = () => {
    void plans.refetch();
    void me.refetch();
    void subscription.refetch();
  };

  // Любой из трёх сбоев — экран ошибки. Показывать каталог, не зная ни
  // текущего тарифа, ни доступности trial, значит утверждать неправду:
  // отсутствие данных у этого экрана неотличимо от отрицательного ответа.
  const error = plans.error ?? me.error ?? subscription.error;
  if (error) {
    return <ErrorState error={error} onRetry={retryAll} />;
  }

  const sub = subscription.data ?? null;
  const live = isLive(sub);
  const currentCode = sub && live ? sub.plan.code : null;
  const catalog = plans.data ?? [];

  /** «30 дней · 3 устройства · 200 ГБ» — склонения из каталога plural.ts. */
  function planSummary(plan: Plan): string {
    return [
      tPlural("unit.day", plan.duration_days),
      tPlural("unit.device", plan.device_limit),
      plan.traffic_limit_bytes === null
        ? t("plans.unlimitedTraffic")
        : formatBytes(plan.traffic_limit_bytes, lang),
    ].join(" · ");
  }

  return (
    <div>
      <Note className="px-1 pt-3">{t("plans.subtitle")}</Note>

      {catalog.length === 0 ? (
        <Card className="mt-3.5 p-4">
          <Note>{t("plans.empty")}</Note>
        </Card>
      ) : (
        <Card className="mt-3.5">
          {catalog.map((plan) => {
            const current = plan.code === currentCode;
            return (
              <Cell
                key={plan.code}
                highlighted={current}
                icon={
                  <CellIcon tone={current ? "solid" : "accent"}>
                    {plan.device_limit}
                  </CellIcon>
                }
                title={
                  <>
                    {plan.name}
                    {current && <Badge>{t("plans.currentShort")}</Badge>}
                  </>
                }
                subtitle={planSummary(plan)}
                value={
                  <span className={current ? "text-accent-700" : undefined}>
                    {formatMoney(plan.price_amount, plan.currency, lang)}
                  </span>
                }
                chevron
                // Действующий тариф не продают повторно: его нажатие —
                // это продление, единственное, что с ним можно сделать.
                onClick={() =>
                  navigate(current ? ROUTES.renew : ROUTES.checkout(plan.code))
                }
              />
            );
          })}
        </Card>
      )}

      {/* Пробный период предлагается только тому, у кого нет действующей
          подписки: поверх оплаченного тарифа он бессмыслен. */}
      {!live && (
        <>
          <SectionLabel>{t("plans.trialTitle")}</SectionLabel>
          <Card className="p-4">
            <Note>
              {t("plans.trialBody", {
                days: tPlural("unit.day", TRIAL_PREVIEW.duration_days),
                traffic: formatBytes(TRIAL_PREVIEW.traffic_limit_bytes, lang),
              })}
            </Note>

            {me.data?.trial_available ? (
              <Button
                className="mt-3.5"
                loading={startTrial.isPending}
                onClick={() =>
                  startTrial.mutate(undefined, {
                    // Подписка уже есть — показывать её должен главный экран,
                    // а не список тарифов, где выбирать больше нечего.
                    onSuccess: () => navigate(ROUTES.home),
                  })
                }
              >
                {t("plans.trialStart")}
              </Button>
            ) : (
              <Note className="mt-2">{t("plans.trialUsed")}</Note>
            )}

            {startTrial.isError && (
              <Note tone="danger" className="mt-2">
                {t(startTrial.error.messageKey())}
              </Note>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function PlansSkeleton() {
  return (
    <div className="space-y-3 pt-3">
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-[248px] w-full rounded-card" />
      <Skeleton className="h-24 w-full rounded-card" />
    </div>
  );
}
