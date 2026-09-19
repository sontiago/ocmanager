import { Button } from "./Button";
import { Card } from "./Card";
import { Cell } from "./Cell";
import { Mono } from "./Mono";
import { Note } from "./Note";
import { StatusIcon } from "./StatusIcon";

interface ErrorStateProps {
  code?: string;
  onRetry?: () => void;
  onSupport?: () => void;
}

const T = {
  title: "Не получилось",
  // Образец тона: что сломалось → что ЦЕЛО → что будет дальше.
  body: "Сервер выдачи ключей недоступен. Подписка и оплата не затронуты — деньги на месте, доступ работает. Запрос сохранён и выполнится сам, как только сервер вернётся.",
  code: "Код",
  retry: "Повторить",
  support: "Написать в поддержку",
};

export function ErrorState({
  code = "NODE_DEGRADED",
  onRetry,
  onSupport,
}: ErrorStateProps) {
  return (
    <div className="px-1 pt-[26px]">
      <StatusIcon kind="bang" />
      <div className="mt-5 mb-2 text-[28px] font-extrabold leading-[1.12] tracking-[-0.025em]">
        {T.title}
      </div>
      <Note size="lg">{T.body}</Note>

      <Card className="mt-4">
        <Cell title={T.code} value={<Mono>{code}</Mono>} />
      </Card>

      {onRetry && (
        <Button className="mt-[18px]" onClick={onRetry}>
          {T.retry}
        </Button>
      )}
      {onSupport && (
        <Button variant="secondary" className="mt-2.5" onClick={onSupport}>
          {T.support}
        </Button>
      )}
    </div>
  );
}
