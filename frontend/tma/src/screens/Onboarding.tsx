import { useNavigate } from "react-router";
import { ROUTES } from "../app/routes";
import { TRIAL } from "./demo";
import { Button } from "../ui/Button";
import { Callout } from "../ui/Callout";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { Note } from "../ui/Note";

const T = {
  title: ["Доступ", "за две минуты"],
  steps: [
    { title: "Выберите тариф", body: "Срок, число устройств, трафик" },
    { title: "Оплатите в Tribute", body: "Доступ включится сам" },
    { title: "Получите ключ", body: "И инструкцию под свою систему" },
  ],
  trialTitle: "Пробный период",
  trial: (d: number, gb: number) =>
    `${d} дня, ${gb} ГБ, одно устройство. Без оплаты, один раз на аккаунт.`,
  start: "Начать пробный период",
  seePlans: "Посмотреть тарифы",
};

export function Onboarding() {
  const navigate = useNavigate();

  return (
    // h-full + flex-col: содержимое растягивается, кнопки прижимаются к низу.
    <div className="flex h-full flex-col">
      <div className="flex-1">
        <div className="px-1 pt-4.5 text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em]">
          {T.title[0]}
          <br />
          {T.title[1]}
        </div>

        <Card className="mt-[22px]">
          {T.steps.map((step, index) => (
            <Cell
              key={step.title}
              icon={<CellIcon>{String(index + 1).padStart(2, "0")}</CellIcon>}
              title={step.title}
              subtitle={step.body}
            />
          ))}
        </Card>

        <Callout>
          <div className="text-[15px] font-semibold">{T.trialTitle}</div>
          <Note className="mt-0.5">
            {T.trial(TRIAL.days, TRIAL.traffic_gb)}
          </Note>
        </Callout>
      </div>

      <div className="pt-4">
        <Button onClick={() => navigate(ROUTES.home)}>{T.start}</Button>
        <Button
          variant="secondary"
          className="mt-2.5"
          onClick={() => navigate(ROUTES.plans)}
        >
          {T.seePlans}
        </Button>
      </div>
    </div>
  );
}
