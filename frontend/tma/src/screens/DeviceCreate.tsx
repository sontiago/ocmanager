import { useNavigate } from "react-router";
import { ROUTES } from "../app/routes";
import { PLATFORM_INFO, SUBSCRIPTION, DEVICES, type Platform } from "./demo";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { Note } from "../ui/Note";
import { SectionLabel } from "../ui/SectionLabel";

const T = {
  intro:
    "Выберите систему устройства — от неё зависит формат ключа и инструкция.",
  nameLabel: "НАЗВАНИЕ",
  note: (left: number) =>
    `Останется ${left} из ${SUBSCRIPTION.device_limit} свободных слотов. Слот освобождается отзывом ключа.`,
};

const ORDER: Platform[] = ["ios", "android", "windows", "macos"];

export function DeviceCreate() {
  const navigate = useNavigate();
  const slotsLeft = SUBSCRIPTION.device_limit - DEVICES.length - 1;

  return (
    <div>
      <Note className="px-1 pt-3">{T.intro}</Note>

      <Card className="mt-3.5">
        {ORDER.map((platform) => {
          const info = PLATFORM_INFO[platform];
          return (
            <Cell
              key={platform}
              icon={<CellIcon small={!info.isApple}>{info.badge}</CellIcon>}
              title={info.label}
              subtitle={info.client}
              chevron
              onClick={() => navigate(ROUTES.deviceKey(platform))}
            />
          );
        })}
      </Card>

      <SectionLabel>{T.nameLabel}</SectionLabel>
      <Card className="px-2.5 py-1.5">
        <input
          defaultValue="iPhone 15"
          readOnly
          className="min-h-11 w-full bg-transparent px-2 text-[15px] outline-none"
        />
      </Card>

      <Note className="px-1 pt-3">{T.note(Math.max(0, slotsLeft))}</Note>
    </div>
  );
}
