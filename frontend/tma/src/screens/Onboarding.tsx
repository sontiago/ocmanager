import { useEffect } from "react";
import { useNavigate } from "react-router";
import { useMe, useStartTrial, useSubscription } from "../api/hooks";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { formatBytes } from "../lib/format";
import { TRIAL_PREVIEW } from "../lib/trial";
import { Button } from "../ui/Button";
import { Callout } from "../ui/Callout";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { Note } from "../ui/Note";

const STEPS = [
  { title: "onboarding.step1Title", body: "onboarding.step1Body" },
  { title: "onboarding.step2Title", body: "onboarding.step2Body" },
  { title: "onboarding.step3Title", body: "onboarding.step3Body" },
] as const;

export function Onboarding() {
  const navigate = useNavigate();
  const { t, tPlural, lang } = useTranslation();

  const me = useMe();
  const subscription = useSubscription();
  const startTrial = useStartTrial();

  // Экран для того, у кого ещё ничего нет. Если подписка уже появилась —
  // вернулись по истории или набрали адрес руками — рассказывать нечего.
  useEffect(() => {
    if (subscription.data) navigate(ROUTES.home, { replace: true });
  }, [subscription.data, navigate]);

  return (
    // h-full + flex-col: содержимое растягивается, кнопки прижимаются к низу.
    // Единственный экран приложения с прижатым футером — здесь выбор и есть
    // всё содержание, и он не должен уезжать за край.
    <div className="flex h-full flex-col">
      <div className="flex-1">
        <div className="px-1 pt-4.5 text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em]">
          {/* Каждая строка — свой узел: иначе текстовые узлы склеиваются
              в «Доступза две минуты» при выделении и в поиске по тексту. */}
          <span>{t("onboarding.title1")}</span>
          <br />
          <span>{t("onboarding.title2")}</span>
        </div>

        <Card className="mt-[22px]">
          {STEPS.map((step, index) => (
            <Cell
              key={step.title}
              icon={<CellIcon>{String(index + 1).padStart(2, "0")}</CellIcon>}
              title={t(step.title)}
              subtitle={t(step.body)}
            />
          ))}
        </Card>

        {me.data?.trial_available && (
          <Callout>
            <div className="text-[15px] font-semibold">
              {t("plans.trialTitle")}
            </div>
            <Note className="mt-0.5">
              {t("plans.trialBody", {
                days: tPlural("unit.day", TRIAL_PREVIEW.duration_days),
                traffic: formatBytes(TRIAL_PREVIEW.traffic_limit_bytes, lang),
              })}
            </Note>
          </Callout>
        )}

        {startTrial.isError && (
          <Note tone="danger" className="px-1 pt-3">
            {t(startTrial.error.messageKey())}
          </Note>
        )}
      </div>

      <div className="pt-4">
        {me.data?.trial_available && (
          <Button
            className="mb-2.5"
            loading={startTrial.isPending}
            onClick={() =>
              startTrial.mutate(undefined, {
                onSuccess: () => navigate(ROUTES.home),
              })
            }
          >
            {t("plans.trialStart")}
          </Button>
        )}

        <Button
          variant={me.data?.trial_available ? "secondary" : "primary"}
          onClick={() => navigate(ROUTES.plans)}
        >
          {t("subscription.choosePlan")}
        </Button>
      </div>
    </div>
  );
}
