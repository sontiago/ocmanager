import { useState } from "react";
import { useNavigate } from "react-router";
import { useDevices, useRevokeDevice, useSubscription } from "../api/hooks";
import type { Device } from "../api/types";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { formatBytes, formatRelative } from "../lib/format";
import { canIssueDevice, isLive } from "../lib/subscription";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { Note } from "../ui/Note";
import { SectionLabel } from "../ui/SectionLabel";
import { Sheet } from "../ui/Sheet";
import { Skeleton } from "../ui/Skeleton";
import { StatusIcon } from "../ui/StatusIcon";
import { PLATFORM_BADGE } from "./platforms";

export function Devices() {
  const navigate = useNavigate();
  const { t, lang } = useTranslation();

  const devices = useDevices();
  const subscription = useSubscription();
  const revoke = useRevokeDevice();

  // Лист живёт в двух режимах: выбор действия и подтверждение отзыва.
  // Отдельного состояния «какое устройство» хватает на оба.
  const [selected, setSelected] = useState<Device | null>(null);
  const [confirming, setConfirming] = useState(false);

  if (devices.isPending || subscription.isPending) return <DevicesSkeleton />;

  const error = devices.error ?? subscription.error;
  if (error) {
    return (
      <ErrorState
        error={error}
        onRetry={() => {
          void devices.refetch();
          void subscription.refetch();
        }}
      />
    );
  }

  const list = devices.data ?? [];
  const sub = subscription.data ?? null;
  const canAdd = canIssueDevice(sub);

  const closeSheet = () => {
    setSelected(null);
    setConfirming(false);
  };

  function describe(device: Device): string {
    const state = device.is_online
      ? t("devices.online")
      : device.last_seen_at
        ? t("devices.lastSeen", {
            when: formatRelative(device.last_seen_at, lang),
          })
        : t("devices.neverConnected");

    return `${state} · ${formatBytes(device.traffic_used_bytes, lang)}`;
  }

  // Пусто по двум разным причинам, и выход из них разный: без подписки
  // выпускать нечего, и звать в выпуск ключа — тупик на 409.
  if (list.length === 0) {
    return (
      <EmptyState
        icon={<StatusIcon kind="plus" />}
        title={t("devices.empty")}
        body={canAdd ? t("devices.emptyBody") : t("subscription.noneBody")}
        action={
          canAdd ? (
            <Button onClick={() => navigate(ROUTES.deviceNew)}>
              {t("devices.add")}
            </Button>
          ) : (
            <Button onClick={() => navigate(ROUTES.plans)}>
              {t("subscription.choosePlan")}
            </Button>
          )
        }
      />
    );
  }

  return (
    <div>
      <SectionLabel>
        {t("devices.slots", {
          used: list.length,
          limit: sub?.device_limit ?? list.length,
        })}
      </SectionLabel>

      <Card>
        {list.map((device) => (
          <Cell
            key={device.id}
            icon={
              // iOS оставлен крупным: это единственный бейдж-марка,
              // остальные — сокращения и в полный кегль не читаются.
              <CellIcon small={device.platform !== "ios"}>
                {PLATFORM_BADGE[device.platform]}
              </CellIcon>
            }
            title={device.name}
            subtitle={describe(device)}
            chevron
            onClick={() => setSelected(device)}
          />
        ))}

        {canAdd && (
          <Cell
            icon={<CellIcon tone="neutral">+</CellIcon>}
            title={t("devices.freeSlot")}
            subtitle={t("devices.freeSlotBody")}
            chevron
            onClick={() => navigate(ROUTES.deviceNew)}
          />
        )}
      </Card>

      {!canAdd && isLive(sub) && (
        <Note className="px-1 pt-3">{t("devices.limitReached")}</Note>
      )}

      <Note className="px-1 pt-3">{t("devices.note")}</Note>

      {/* Ошибка отзыва живёт на экране, а не в закрытом листе: иначе
          человек увидит, что устройство осталось, и не поймёт почему. */}
      {revoke.isError && (
        <Note tone="danger" className="px-1 pt-3">
          {t(revoke.error.messageKey())}
        </Note>
      )}

      <Sheet
        open={selected !== null}
        onClose={closeSheet}
        title={confirming ? t("devices.revokeTitle") : (selected?.name ?? "")}
      >
        {selected && !confirming && (
          <>
            <Cell
              title={t("devices.instructions")}
              chevron
              onClick={() => navigate(ROUTES.deviceGuide(selected.platform))}
            />
            <Cell
              title={t("devices.revoke")}
              destructive
              onClick={() => setConfirming(true)}
            />
          </>
        )}

        {selected && confirming && (
          <div className="px-4 pt-1 pb-2">
            <Note size="lg">
              {t("devices.revokeBody", { name: selected.name })}
            </Note>
            <Button
              variant="destructive"
              className="mt-4"
              loading={revoke.isPending}
              onClick={() =>
                // onSettled, а не onSuccess: при ошибке лист тоже обязан
                // закрыться — сообщение ждёт человека на экране.
                revoke.mutate(selected.id, { onSettled: closeSheet })
              }
            >
              {t("devices.revokeConfirm")}
            </Button>
            <Button
              variant="secondary"
              className="mt-2"
              onClick={() => setConfirming(false)}
            >
              {t("common.cancel")}
            </Button>
          </div>
        )}
      </Sheet>
    </div>
  );
}

function DevicesSkeleton() {
  return (
    <div className="space-y-3 pt-4">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-44 w-full rounded-card" />
      <Skeleton className="h-16 w-full" />
    </div>
  );
}
