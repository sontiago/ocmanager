import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./errors";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Мобильная сеть: два повтора, но только там, где повтор осмыслен.
        retry: (failureCount, error) =>
          error instanceof ApiError && error.retryable && failureCount < 2,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
        staleTime: 30_000,
        // Возврат в Mini App после оплаты — самый частый способ обновить данные.
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
      },
      mutations: {
        // Мутации не повторяем никогда: выпуск устройства не идемпотентен.
        retry: false,
      },
    },
  });
}
