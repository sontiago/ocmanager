import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";
import type { ApiClient } from "../client";
import { useApiClient } from "../session";

/** Мутация к API; после успеха инвалидирует перечисленные ключи (префиксом). */
export function useApiMutation<V, R = void>(
  run: (client: ApiClient, vars: V) => Promise<R>,
  invalidate: readonly QueryKey[],
  options: { gcTime?: number } = {},
) {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: V) => run(client, vars),
    gcTime: options.gcTime,
    onSuccess: async () => {
      await Promise.all(invalidate.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
    },
  });
}
