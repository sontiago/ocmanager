import { useNavigate } from "react-router";
import { ROUTES } from "../app/routes";
import { PLANS, TRIAL, type DemoPlan } from "./demo";
import { formatGbWhole, formatMoney, plural } from "../lib/format";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { Note } from "../ui/Note";
import { SectionLabel } from "../ui/SectionLabel";

const T = {
  intro:
    "Оплата через Tribute. Продление автоматическое, ключи не перевыпускаются.",
  current: "ТЕКУЩИЙ",
  trialLabel: "ПРОБНЫЙ ПЕРИОД",
  trial: (d: number, gb: number, used: string) =>
    `${d} ${plural(d, "день", "дня", "дней")} и ${gb} ГБ на одно устройство — использован ${used}. Один раз на аккаунт Telegram.`,
};

function planSubtitle(plan: DemoPlan): string {
  const days = `${plan.duration_days} ${plural(plan.duration_days, "день", "дня", "дней")}`;
  const devices = `${plan.device_limit} ${plural(plan.device_limit, "устройство", "устройства", "устройств")}`;
  const gb = formatGbWhole(plan.traffic_limit_bytes);
  return `${days} · ${devices} · ${gb} ГБ`;
}

export function Plans() {
  const navigate = useNavigate();

  return (
    <div>
      <Note className="px-1 pt-3">{T.intro}</Note>

      <Card className="mt-3.5">
        {PLANS.map((plan) => (
          <Cell
            key={plan.code}
            highlighted={plan.is_current}
            icon={
              <CellIcon tone={plan.is_current ? "solid" : "accent"}>
                {plan.device_limit}
              </CellIcon>
            }
            title={
              <>
                {plan.name}
                {plan.is_current && <Badge>{T.current}</Badge>}
              </>
            }
            subtitle={planSubtitle(plan)}
            value={
              <span className={plan.is_current ? "text-accent-700" : undefined}>
                {formatMoney(plan.price_amount, plan.currency, "ru")}
              </span>
            }
            chevron
            onClick={() =>
              navigate(
                plan.is_current ? ROUTES.renew : ROUTES.checkout(plan.code),
              )
            }
          />
        ))}
      </Card>

      <SectionLabel>{T.trialLabel}</SectionLabel>
      <Card className="p-4">
        <Note>{T.trial(TRIAL.days, TRIAL.traffic_gb, TRIAL.used_at)}</Note>
      </Card>
    </div>
  );
}
