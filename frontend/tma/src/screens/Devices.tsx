import { useNavigate } from "react-router";
import { ROUTES } from "../app/routes";
import { DEVICES, PLATFORM_INFO, SUBSCRIPTION } from "./demo";
import { formatGb } from "../lib/format";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { Note } from "../ui/Note";
import { SectionLabel } from "../ui/SectionLabel";
import { StatusIcon } from "../ui/StatusIcon";

const T = {
  slots: (used: number, total: number) => `ЗАНЯТО ${used} ИЗ ${total} СЛОТОВ`,
  freeSlot: "Свободный слот",
  freeSlotSub: "Выпустить ключ на новое устройство",
  actions: "ДЕЙСТВИЯ",
  revoke: "Отозвать ключ",
  note: "Один ключ работает на одном устройстве. Отозванный ключ перестаёт подключаться сразу, слот освобождается.",
  emptyTitle: "Устройств пока нет",
  emptyBody:
    "Подписка активна, но ни один ключ не выпущен. Выпуск занимает около десяти секунд, ключ приходит одноразовой ссылкой.",
  emptyAction: "Выпустить первый ключ",
};

export function Devices() {
  const navigate = useNavigate();
  const hasFreeSlot = DEVICES.length < SUBSCRIPTION.device_limit;

  // Пустое состояние — не заглушка, а полноценный экран: он объясняет,
  // сколько займёт выпуск и как придёт ключ. Это тон всего прототипа.
  if (DEVICES.length === 0) {
    return (
      <div className="px-1 pt-[34px]">
        <StatusIcon kind="plus" />
        <div className="mt-5 mb-2 text-[26px] font-extrabold leading-[1.15] tracking-[-0.02em]">
          {T.emptyTitle}
        </div>
        <Note size="lg">{T.emptyBody}</Note>
        <Button
          className="mt-[18px]"
          onClick={() => navigate(ROUTES.deviceNew)}
        >
          {T.emptyAction}
        </Button>
      </div>
    );
  }

  return (
    <div>
      <SectionLabel>
        {T.slots(DEVICES.length, SUBSCRIPTION.device_limit)}
      </SectionLabel>
      <Card>
        {DEVICES.map((device) => {
          const info = PLATFORM_INFO[device.platform];
          return (
            <Cell
              key={device.id}
              icon={
                <CellIcon small={info.badge.length > 3 || !info.isApple}>
                  {info.badge}
                </CellIcon>
              }
              title={device.name}
              subtitle={`${device.last_seen} · ${formatGb(device.traffic_used_bytes)} ГБ · ${device.username}`}
              chevron
              onClick={() => navigate(ROUTES.deviceGuide(device.platform))}
            />
          );
        })}
        {hasFreeSlot && (
          <Cell
            icon={<CellIcon tone="neutral">+</CellIcon>}
            title={T.freeSlot}
            subtitle={T.freeSlotSub}
            chevron
            onClick={() => navigate(ROUTES.deviceNew)}
          />
        )}
      </Card>

      <SectionLabel>{T.actions}</SectionLabel>
      <Card>
        <Cell
          title={<span className="text-accent-700">{T.revoke}</span>}
          chevron
          onClick={() => console.log("отзыв ключа — этап 3")}
        />
      </Card>

      <Note className="px-1 pt-3">{T.note}</Note>
    </div>
  );
}
