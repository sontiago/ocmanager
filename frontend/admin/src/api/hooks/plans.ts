import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { S } from "../types";

export function usePlans() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.plans,
    queryFn: () => client.get<S<"PlanOut">[]>("/plans"),
  });
}
