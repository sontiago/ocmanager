import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { S } from "../types";
import { useApiMutation } from "./mutate";

export function useSettings() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => client.get<S<"SettingsOut">>("/settings"),
  });
}

export const usePatchSettings = () =>
  useApiMutation<Record<string, unknown>, S<"SettingsOut">>(
    (c, patch) => c.patch("/settings", patch),
    [queryKeys.settings],
  );
