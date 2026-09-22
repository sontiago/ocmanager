import { Navigate, useNavigate, useParams } from "react-router";
import { useConnection } from "../api/hooks";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { openExternal } from "../telegram/links";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { CopyButton } from "../ui/CopyButton";
import { ErrorState } from "../ui/ErrorState";
import { Mono } from "../ui/Mono";
import { SectionLabel } from "../ui/SectionLabel";
import { Skeleton } from "../ui/Skeleton";
import { STEP_KEYS, STORE_LINKS } from "./instructionSteps";
import { PLATFORM_LABEL, isPlatform } from "./platforms";

export function Instructions() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { platform } = useParams();

  const connection = useConnection();

  // Адрес набрали руками или он остался в старой ссылке: показывать
  // инструкцию «под ничто» нельзя, уводим в список устройств.
  if (!isPlatform(platform)) return <Navigate to={ROUTES.devices} replace />;

  if (connection.isPending) return <InstructionsSkeleton />;

  if (connection.error) {
    return (
      <ErrorState
        error={connection.error}
        onRetry={() => void connection.refetch()}
      />
    );
  }

  const storeLink = STORE_LINKS[platform];

  return (
    <div>
      <SectionLabel>{t("instructions.server")}</SectionLabel>
      <Card className="flex items-center justify-between gap-2.5 p-4">
        <Mono className="min-w-0 break-all text-[13.5px]">
          {connection.data?.gateway_url}
        </Mono>
        <CopyButton value={connection.data?.gateway_url ?? ""} />
      </Card>

      <SectionLabel>
        {PLATFORM_LABEL[platform]} · {t("instructions.title")}
      </SectionLabel>
      <Card>
        {STEP_KEYS[platform].map((key, index) => (
          <Cell
            key={key}
            align="start"
            icon={<CellIcon>{String(index + 1).padStart(2, "0")}</CellIcon>}
            title={t(key)}
          />
        ))}
      </Card>

      {/* Под Linux клиент ставится пакетным менеджером — магазина нет. */}
      {storeLink && (
        <Button
          variant="secondary"
          className="mt-[18px]"
          onClick={() => openExternal(storeLink)}
        >
          {t("instructions.openStore")}
        </Button>
      )}

      <Button
        className={storeLink ? "mt-2.5" : "mt-[18px]"}
        onClick={() => navigate(ROUTES.devices)}
      >
        {t("common.done")}
      </Button>
    </div>
  );
}

function InstructionsSkeleton() {
  return (
    <div className="space-y-3 pt-4">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-16 w-full rounded-card" />
      <Skeleton className="h-60 w-full rounded-card" />
    </div>
  );
}
