import type { ReactNode } from "react";
import { useMe } from "../api/hooks";
import { env } from "../env";
import { useTranslation } from "../i18n/useTranslation";
import { getInitDataRaw } from "../telegram/auth";
import { openInTelegram } from "../telegram/links";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { Skeleton } from "../ui/Skeleton";
import { StatusIcon } from "../ui/StatusIcon";

/** Заглушки занимают окно целиком: ни шапки, ни таб-бара у них нет. */
function Screen({ children }: { children: ReactNode }) {
  return (
    <div className="h-full overflow-y-auto bg-bg px-4 pt-[calc(var(--safe-top)+8px)] pb-[calc(22px+var(--safe-bottom))] text-ink">
      {children}
    </div>
  );
}

export function Gate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();

  const hasInitData = getInitDataRaw() !== undefined;
  // enabled:false — без initData запрос гарантированно получит 401,
  // и отправлять его означает только шуметь в логах бэкенда.
  const me = useMe({ enabled: hasInitData });

  // Порядок проверок обязателен: у отключённого запроса isPending остаётся
  // true навсегда, и проверка initData обязана идти первой — иначе экран
  // застрянет на скелете до закрытия приложения.
  if (!hasInitData) {
    return (
      <Screen>
        <EmptyState
          icon={<StatusIcon kind="bang" />}
          title={t("gate.outsideTelegram")}
          body={t("gate.outsideTelegramBody")}
        />
      </Screen>
    );
  }

  if (me.isPending) {
    return (
      <Screen>
        <div className="space-y-3 pt-4">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-16 w-1/2" />
          <Skeleton className="h-28 w-full rounded-card" />
        </div>
      </Screen>
    );
  }

  if (me.isError) {
    return (
      <Screen>
        <ErrorState error={me.error} onRetry={() => void me.refetch()} />
      </Screen>
    );
  }

  // Блокировка — не ошибка транспорта: повторять запрос бессмысленно,
  // человеку нужен выход к людям.
  if (me.data?.is_blocked) {
    return (
      <Screen>
        <EmptyState
          icon={<StatusIcon kind="bang" />}
          title={t("gate.blocked")}
          body={t("gate.blockedBody")}
          action={
            <Button
              onClick={() =>
                openInTelegram(
                  `https://t.me/${env.supportHandle.replace(/^@/, "")}`,
                )
              }
            >
              {t("error.support")}
            </Button>
          }
        />
      </Screen>
    );
  }

  return <>{children}</>;
}
