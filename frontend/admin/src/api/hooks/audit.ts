import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { Page, S } from "../types";

export interface AuditFilters {
  actor_type?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  since?: string;
  until?: string;
  limit: number;
  offset: number;
}

export function useAudit(filters: AuditFilters) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.audit({ ...filters }),
    queryFn: () => client.get<Page<S<"AuditRow">>>("/audit", { ...filters }),
    placeholderData: (prev) => prev,
  });
}
