import { useState } from "react";
import { useNavigate } from "react-router";
import { useCreateDevice, useSubscription } from "../api/hooks";
import type { Platform } from "../api/types";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { canIssueDevice, isLive } from "../lib/subscription";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { Note } from "../ui/Note";
import { SectionLabel } from "../ui/SectionLabel";
import { Skeleton } from "../ui/Skeleton";
import { StatusIcon } from "../ui/StatusIcon";
import { PLATFORMS, PLATFORM_BADGE, PLATFORM_LABEL } from "./platforms";
import { stashIssued } from "./secretVault";

export function DeviceCreate() {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const subscription = useSubscription();
  const createDevice = useCreateDevice();

  const [platform, setPlatform] = useState<Platform | null>(null);
  const [name, setName] = useState("");

  if (subscription.isPending) return <DeviceCreateSkeleton />;

  if (subscription.error) {
    return (
      <ErrorState
        error={subscription.error}
        onRetry={() => void subscription.refetch()}
      />
    );
  }

  const sub = subscription.data ?? null;

  // Форма, которая заведомо упрётся в 409, хуже объяснения.
  if (!canIssueDevice(sub)) {
    const live = isLive(sub);
    return (
      <EmptyState
        icon={<StatusIcon kind="bang" />}
        title={live ? t("devices.limitReached") : t("subscription.none")}
        body={live ? t("devices.note") : t("subscription.noneBody")}
        action={
          <Button
            onClick={() => navigate(live ? ROUTES.devices : ROUTES.plans)}
          >
            {live ? t("devices.manage") : t("subscription.choosePlan")}
          </Button>
        }
      />
    );
  }

  const ready = platform !== null && name.trim().length > 0;

  const submit = () => {
    if (!platform || !ready) return;
    createDevice.mutate(
      { name: name.trim(), platform },
      {
        onSuccess: (issued) => {
          // Секрет уходит в память модуля, а не в адрес и не в state роутера.
          stashIssued(issued);
          // replace: «назад» с экрана ключа не должен возвращать на форму,
          // повторный выпуск съел бы ещё один слот.
          navigate(ROUTES.deviceKey(platform), { replace: true });
        },
      },
    );
  };

  return (
    <div>
      <Note className="px-1 pt-3">{t("deviceCreate.intro")}</Note>

      <div
        role="radiogroup"
        aria-label={t("deviceCreate.pickPlatform")}
        className="mt-3.5"
      >
        <Card>
          {PLATFORMS.map((value) => (
            <Cell
              key={value}
              icon={
                <CellIcon small={value !== "ios"}>
                  {PLATFORM_BADGE[value]}
                </CellIcon>
              }
              title={PLATFORM_LABEL[value]}
              selected={platform === value}
              onClick={() => {
                setPlatform(value);
                // Имя подставляем, пока человек его не трогал: как только
                // он что-то вписал, переписывать введённое нельзя.
                const untouched =
                  name === "" ||
                  PLATFORMS.some((p) => PLATFORM_LABEL[p] === name);
                if (untouched) setName(PLATFORM_LABEL[value]);
              }}
            />
          ))}
        </Card>
      </div>

      <SectionLabel>
        <label htmlFor="device-name">{t("deviceCreate.name")}</label>
      </SectionLabel>
      <Card className="px-2.5 py-1.5">
        <input
          id="device-name"
          type="text"
          value={name}
          maxLength={40}
          placeholder={t("deviceCreate.namePlaceholder")}
          onChange={(event) => setName(event.target.value)}
          className="min-h-11 w-full bg-transparent px-2 text-[15px] outline-none"
        />
      </Card>

      <Button
        className="mt-[18px]"
        loading={createDevice.isPending}
        disabled={!ready}
        onClick={submit}
      >
        {createDevice.isPending
          ? t("deviceCreate.issuing")
          : t("deviceCreate.submit")}
      </Button>

      {createDevice.isError && (
        <Note tone="danger" className="px-1 pt-3">
          {t(createDevice.error.messageKey())}
        </Note>
      )}
    </div>
  );
}

function DeviceCreateSkeleton() {
  return (
    <div className="space-y-3 pt-4">
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-64 w-full rounded-card" />
      <Skeleton className="h-14 w-full rounded-btn" />
    </div>
  );
}
