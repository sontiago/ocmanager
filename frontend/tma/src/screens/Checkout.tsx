import { useNavigate, useParams } from "react-router";
import { useCheckoutLink, usePlans } from "../api/hooks";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { formatMoney } from "../lib/format";
import { Button, ButtonLink } from "../ui/Button";
import { Caption } from "../ui/Caption";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { Hero } from "../ui/Hero";
import { Note } from "../ui/Note";
import { Skeleton } from "../ui/Skeleton";
import { StatusIcon } from "../ui/StatusIcon";

export function Checkout() {
  const { planCode } = useParams();
  const navigate = useNavigate();
  const { t, tPlural, lang } = useTranslation();

  const plans = usePlans();
  // Ссылку на оплату создаём сразу, как только выяснилось, что тариф существует.
  const checkout = useCheckoutLink(
    planCode,
    plans.data?.some((p) => p.code === planCode) ?? false,
  );

  if (plans.isPending) return <CheckoutSkeleton />;

  if (plans.error) {
    return (
      <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />
    );
  }

  // Адрес мог остаться в истории после того, как тариф сняли с продажи.
  // Сообщение без выхода — тупик, поэтому рядом кнопка в каталог.
  const plan = plans.data?.find((p) => p.code === planCode);
  if (!plan) {
    return (
      <EmptyState
        icon={<StatusIcon kind="bang" />}
        title={t("checkout.notFound")}
        body={t("checkout.notFoundBody")}
        action={
          <Button onClick={() => navigate(ROUTES.plans)}>
            {t("subscription.choosePlan")}
          </Button>
        }
      />
    );
  }

  return (
    <div>
      <div className="px-1 pt-3.5">
        <Caption>{t("checkout.total")}</Caption>
        <Hero size="lg">
          {formatMoney(plan.price_amount, plan.currency, lang)}
        </Hero>
      </div>

      <Card className="mt-5">
        <Cell title={t("checkout.plan")} value={plan.name} />
        <Cell
          title={t("checkout.period")}
          value={tPlural("unit.day", plan.duration_days)}
        />
        {/* Имя провайдера — не перевод, а марка: в каталог i18n не идёт. */}
        <Cell title={t("checkout.method")} value="Tribute" />
        <Cell
          title={t("checkout.autoRenew")}
          value={t("checkout.autoRenewOn")}
        />
      </Card>

      <Note className="px-1 pt-3.5">{t("checkout.note")}</Note>

      {checkout.isPending && (
        <Button className="mt-[18px]" loading>
          {t("checkout.opening")}
        </Button>
      )}

      {checkout.isSuccess && (
        // Обычная ссылка: Telegram откроет Tribute сам, приложение при этом остаётся открытым.
        <ButtonLink className="mt-[18px]" href={checkout.data.checkout_url}>
          {t("checkout.pay")}
        </ButtonLink>
      )}

      {checkout.isError && (
        <>
          <Note tone="danger" className="px-1 pt-3.5">
            {t(checkout.error.messageKey())}
          </Note>
          {checkout.error.retryable && (
            <Button
              className="mt-[18px]"
              onClick={() => void checkout.refetch()}
            >
              {t("common.retry")}
            </Button>
          )}
        </>
      )}
    </div>
  );
}

function CheckoutSkeleton() {
  return (
    <div className="space-y-3 pt-4">
      <Skeleton className="h-4 w-1/4" />
      <Skeleton className="h-14 w-2/3" />
      <Skeleton className="h-52 w-full rounded-card" />
      <Skeleton className="h-14 w-full rounded-btn" />
    </div>
  );
}
