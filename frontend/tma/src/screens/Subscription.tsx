import { useNavigate } from "react-router";
import { ROUTES } from "../app/routes";
import { SUBSCRIPTION, DEVICES } from "./demo";
import { formatGb, formatGbWhole, plural } from "../lib/format";
import { Button } from "../ui/Button";
import { Caption } from "../ui/Caption";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { Hero } from "../ui/Hero";
import { ProgressBar } from "../ui/ProgressBar";
import { QuickActions } from "../ui/QuickActions";
import { SectionLabel } from "../ui/SectionLabel";
import { Note } from "../ui/Note";
import {
  IconArrowUp,
  IconGrid,
  IconHelp,
  IconPhone,
  IconPlus,
  IconRenew,
} from "../ui/icons";

const T = {
  heroCaption: "Доступ активен ещё",
  sub: (plan: string, date: string, auto: string) =>
    `${plan} · до ${date} · автопродление ${auto}`,
  renew: "Продлить",
  device: "Устройство",
  plans: "Тарифы",
  help: "Помощь",
  trafficLabel: "ТРАФИК ЗА ПЕРИОД",
  trafficNote: "Счётчик обнулится 21 сентября вместе с продлением.",
  subscriptionLabel: "ПОДПИСКА",
  devices: "Устройства",
  devicesSub: "iPhone 15, MacBook Air",
  autoRenew: "Автопродление",
  changePlan: "Сменить тариф",
  changePlanSub: "Больше устройств или трафика",
  addDevice: "Добавить устройство",
};

export function Subscription() {
  const navigate = useNavigate();
  const s = SUBSCRIPTION;
  const percent = Math.round(
    (s.traffic_used_bytes / s.traffic_limit_bytes) * 100,
  );
  const auto = s.auto_renew ? "включено" : "выключено";

  return (
    <div>
      <div className="px-1 pt-3.5">
        <Caption>{T.heroCaption}</Caption>
        <Hero tail={plural(s.days_left, "день", "дня", "дней")}>
          {s.days_left}
        </Hero>
        <Note>{T.sub(s.plan_name, s.expires_at, auto)}</Note>
      </div>

      <QuickActions
        items={[
          {
            icon: <IconRenew />,
            label: T.renew,
            onClick: () => navigate(ROUTES.renew),
          },
          {
            icon: <IconPlus />,
            label: T.device,
            onClick: () => navigate(ROUTES.deviceNew),
          },
          {
            icon: <IconGrid size={23} />,
            label: T.plans,
            onClick: () => navigate(ROUTES.plans),
          },
          {
            icon: <IconHelp />,
            label: T.help,
            onClick: () => navigate(ROUTES.account),
          },
        ]}
      />

      <SectionLabel>{T.trafficLabel}</SectionLabel>
      <Card className="p-4">
        <div className="flex items-baseline justify-between">
          <span className="text-2xl font-extrabold tracking-[-0.02em]">
            {formatGb(s.traffic_used_bytes)}{" "}
            <span className="text-sm">
              / {formatGbWhole(s.traffic_limit_bytes)} ГБ
            </span>
          </span>
          <Caption>{percent}%</Caption>
        </div>
        <ProgressBar percent={percent} />
        <Note className="mt-2">{T.trafficNote}</Note>
      </Card>

      <SectionLabel>{T.subscriptionLabel}</SectionLabel>
      <Card>
        <Cell
          icon={
            <CellIcon>
              <IconPhone size={19} />
            </CellIcon>
          }
          title={T.devices}
          subtitle={T.devicesSub}
          value={`${DEVICES.length} / ${s.device_limit}`}
          chevron
          onClick={() => navigate(ROUTES.devices)}
        />
        <Cell
          icon={
            <CellIcon>
              <IconRenew size={19} />
            </CellIcon>
          }
          title={T.autoRenew}
          subtitle="Списание 299 ₽ · 21.09.2026"
          value={auto}
          chevron
          onClick={() => navigate(ROUTES.renew)}
        />
        <Cell
          icon={
            <CellIcon>
              <IconArrowUp size={19} />
            </CellIcon>
          }
          title={T.changePlan}
          subtitle={T.changePlanSub}
          chevron
          onClick={() => navigate(ROUTES.plans)}
        />
      </Card>

      <Button className="mt-[18px]" onClick={() => navigate(ROUTES.deviceNew)}>
        {T.addDevice}
      </Button>
    </div>
  );
}
