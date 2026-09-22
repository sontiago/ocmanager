import { useNavigate } from "react-router";
import { useDevices, useSubscription, useMe } from "../api/hooks";
import type { Subscription as Sub } from "../api/types";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { formatBytes, formatDate, formatMoney } from "../lib/format";
import {
  canIssueDevice,
  daysLeft,
  isLive,
  statusMessageKey,
  trafficPercent,
} from "../lib/subscription";
import { Button } from "../ui/Button";
import { Caption } from "../ui/Caption";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { Hero } from "../ui/Hero";
import { Note } from "../ui/Note";
import { ProgressBar } from "../ui/ProgressBar";
import { SectionLabel } from "../ui/SectionLabel";
import { Skeleton } from "../ui/Skeleton";
import { StatusIcon } from "../ui/StatusIcon";
import { IconArrowUp, IconPhone, IconRenew } from "../ui/icons";
import { useEffect } from "react";

export function Subscription() {
  const navigate = useNavigate();
  const { t, tPlural, lang } = useTranslation();

  const subscription = useSubscription();
  // Список устройств нужен только для подписи строки. Экран его не ждёт:
  // срок и трафик важнее имён и приходят отдельным запросом.
  const devices = useDevices();

  const me = useMe();

  // Новичку с нетронутым пробным периодом показываем онбординг: «Подписки
  // нет» с одной кнопкой ничего не объясняет про продукт. Условие смотрит
  // именно на null — undefined означает «ещё не загрузилось».
  useEffect(() => {
    if (subscription.data === null && me.data?.trial_available) {
      navigate(ROUTES.onboarding, { replace: true });
    }
  }, [subscription.data, me.data, navigate]);

  if (subscription.isPending) return <SubscriptionSkeleton />;

  if (subscription.error) {
    return (
      <ErrorState
        error={subscription.error}
        onRetry={() => void subscription.refetch()}
      />
    );
  }

  const sub = subscription.data;

  if (!sub) {
    return (
      <EmptyState
        icon={<StatusIcon kind="plus" />}
        title={t("subscription.none")}
        body={t("subscription.noneBody")}
        action={
          <Button onClick={() => navigate(ROUTES.plans)}>
            {t("subscription.choosePlan")}
          </Button>
        }
      />
    );
  }

  // Мёртвая подписка: цифра дней бессмысленна, остаётся слово-статус и одно
  // действие. Карточка трафика при этом нужна — именно она объясняет
  // статус «Трафик исчерпан».
  if (!isLive(sub)) {
    // Трафик кончился раньше срока: период ещё идёт, а гигабайты — нет.
    // И объяснение, и действие у этого случая свои.
    const exhausted = sub.status === "exhausted";

    return (
      <div>
        <EmptyState
          icon={<StatusIcon kind="bang" />}
          title={t(statusMessageKey(sub))}
          // Дата уместна только там, где подписка действительно закончилась.
          // У exhausted expires_at лежит в будущем, и «Закончилась
          // 12 октября» было бы неправдой.
          body={
            sub.status === "expired" && sub.expires_at
              ? t("subscription.expiredOn", {
                  date: formatDate(sub.expires_at, lang),
                })
              : undefined
          }
          action={
            <Button onClick={() => navigate(ROUTES.plans)}>
              {t(exhausted ? "subscription.changePlan" : "subscription.renew")}
            </Button>
          }
        />
        {/* Полная полоса объясняет статус «Трафик исчерпан». В остальных
            мёртвых состояниях она ничего не объясняет и только шумит. */}
        {exhausted && <TrafficBlock sub={sub} />}
      </div>
    );
  }

  const left = daysLeft(sub);

  // «Месяц · Действует до 21 сентября 2026 г. · Продлевается автоматически»
  const summary = [sub.plan.name];
  if (sub.expires_at) {
    summary.push(
      t("subscription.expiresOn", { date: formatDate(sub.expires_at, lang) }),
    );
  }
  summary.push(
    t(
      sub.auto_renew ? "subscription.autoRenewOn" : "subscription.autoRenewOff",
    ),
  );

  return (
    <div>
      <div className="px-1 pt-3.5">
        {Number.isFinite(left) ? (
          <>
            <Caption>{t("subscription.accessLeft")}</Caption>
            <Hero tail={tPlural("unit.dayBare", left)}>{left}</Hero>
          </>
        ) : (
          // Подписка без даты окончания — в спецификации не описана, но
          // тип её допускает. Вместо пустого героя показываем статус.
          <Hero size="sm">{t(statusMessageKey(sub))}</Hero>
        )}
        <Note>{summary.join(" · ")}</Note>
      </div>

      <TrafficBlock sub={sub} />

      <SectionLabel>{t("subscription.title")}</SectionLabel>
      <Card>
        <Cell
          icon={
            <CellIcon>
              <IconPhone size={19} />
            </CellIcon>
          }
          title={t("devices.title")}
          subtitle={
            devices.data?.length
              ? devices.data.map((device) => device.name).join(", ")
              : t("devices.empty")
          }
          value={`${sub.devices_used} / ${sub.device_limit}`}
          chevron
          onClick={() => navigate(ROUTES.devices)}
        />
        <Cell
          icon={
            <CellIcon>
              <IconRenew size={19} />
            </CellIcon>
          }
          title={t("subscription.autoRenew")}
          // Сумма — единственное, чего нет больше нигде на экране. Дату
          // не дублируем: строка под героем уже называет её.
          subtitle={
            sub.auto_renew
              ? t("subscription.nextCharge", {
                  price: formatMoney(
                    sub.plan.price_amount,
                    sub.plan.currency,
                    lang,
                  ),
                })
              : undefined
          }
          value={t(sub.auto_renew ? "subscription.on" : "subscription.off")}
          chevron
          onClick={() => navigate(ROUTES.renew)}
        />
        <Cell
          icon={
            <CellIcon>
              <IconArrowUp size={19} />
            </CellIcon>
          }
          title={t("subscription.changePlan")}
          subtitle={t("subscription.changePlanBody")}
          chevron
          onClick={() => navigate(ROUTES.plans)}
        />
      </Card>

      {canIssueDevice(sub) ? (
        <Button
          className="mt-[18px]"
          onClick={() => navigate(ROUTES.deviceNew)}
        >
          {t("devices.add")}
        </Button>
      ) : (
        // Кнопка, которая заведомо упрётся в 409, хуже отсутствия кнопки.
        <Note className="px-1 pt-[18px]">{t("devices.limitReached")}</Note>
      )}
    </div>
  );
}

function TrafficBlock({ sub }: { sub: Sub }) {
  const { t, lang } = useTranslation();
  const limit = sub.traffic_limit_bytes;
  const percent = trafficPercent(sub);

  return (
    <>
      <SectionLabel>{t("subscription.traffic")}</SectionLabel>
      <Card className="p-4">
        {limit === null || percent === null ? (
          <div className="text-2xl font-extrabold tracking-[-0.02em]">
            {t("subscription.trafficUnlimited")}
          </div>
        ) : (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-2xl font-extrabold tracking-[-0.02em]">
                {t("subscription.trafficUsed", {
                  used: formatBytes(sub.traffic_used_bytes, lang),
                  limit: formatBytes(limit, lang),
                })}
              </span>
              <Caption>{percent} %</Caption>
            </div>
            <ProgressBar
              percent={percent}
              tone={
                percent >= 95 ? "danger" : percent >= 80 ? "warning" : "normal"
              }
            />
          </>
        )}
      </Card>
    </>
  );
}

function SubscriptionSkeleton() {
  return (
    <div className="space-y-3 pt-4">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-16 w-1/2" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-28 w-full rounded-card" />
      <Skeleton className="h-36 w-full rounded-card" />
    </div>
  );
}
