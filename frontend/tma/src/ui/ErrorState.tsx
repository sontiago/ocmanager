import type { ApiError } from "../api/errors";
import { useTranslation } from "../i18n/useTranslation";
import { Button } from "./Button";
import { Card } from "./Card";
import { Cell } from "./Cell";
import { Mono } from "./Mono";
import { Note } from "./Note";
import { StatusIcon } from "./StatusIcon";

interface ErrorStateProps {
  error: ApiError;
  /** Кнопка повтора появляется только у повторяемых ошибок. */
  onRetry?: () => void;
  onSupport?: () => void;
}

export function ErrorState({ error, onRetry, onSupport }: ErrorStateProps) {
  const { t } = useTranslation();

  return (
    <div className="px-1 pt-[26px]">
      <StatusIcon kind="bang" />
      <div className="mt-5 mb-2 text-[28px] font-extrabold leading-[1.12] tracking-[-0.025em]">
        {t("error.title")}
      </div>
      <Note size="lg">{t(error.messageKey())}</Note>

      <Card className="mt-4">
        <Cell title={t("error.code")} value={<Mono>{error.code}</Mono>} />
      </Card>

      {onRetry && error.retryable && (
        <Button className="mt-[18px]" onClick={onRetry}>
          {t("common.retry")}
        </Button>
      )}
      {onSupport && (
        <Button variant="secondary" className="mt-2.5" onClick={onSupport}>
          {t("error.support")}
        </Button>
      )}
    </div>
  );
}
