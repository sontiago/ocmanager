import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "./mutate";
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

export const useCreatePlan = () =>
  useApiMutation<S<"PlanCreate">, S<"PlanOut">>((c, body) => c.post("/plans", body), [
    queryKeys.plans,
  ]);

export const useUpdatePlan = () =>
  useApiMutation<{ code: string; patch: S<"PlanUpdate"> }, S<"PlanOut">>(
    (c, { code, patch }) => c.patch(`/plans/${code}`, patch),
    [queryKeys.plans],
  );
