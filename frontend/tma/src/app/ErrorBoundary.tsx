import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "../i18n/useTranslation";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { StatusIcon } from "../ui/StatusIcon";

function Crashed() {
  const { t } = useTranslation();
  return (
    <div className="h-full overflow-y-auto bg-bg px-4 pt-[calc(var(--safe-top)+8px)] text-ink">
      <EmptyState
        icon={<StatusIcon kind="bang" />}
        title={t("gate.crashed")}
        body={t("gate.crashedBody")}
        action={
          <Button onClick={() => window.location.reload()}>
            {t("gate.reload")}
          </Button>
        }
      />
    </div>
  );
}

/**
 * Классовый компонент — единственный способ перехватить исключение рендера:
 * хуковой альтернативы componentDidCatch в React нет.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { crashed: boolean }
> {
  state = { crashed: false };

  static getDerivedStateFromError(): { crashed: boolean } {
    return { crashed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Телеметрии на этом этапе нет: логи собираются на бэкенде,
    // фронт оставляет след в консоли клиента.
    console.error(
      "[tma] непойманная ошибка рендера",
      error,
      info.componentStack,
    );
  }

  render(): ReactNode {
    return this.state.crashed ? <Crashed /> : this.props.children;
  }
}
