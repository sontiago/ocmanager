import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { Page, S } from "../types";

export function useReferralStats() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.referrals.stats,
    queryFn: () => client.get<S<"ReferralStats">>("/referrals/stats"),
  });
}

export interface RewardFilters {
  inviter_id?: number;
  limit: number;
  offset: number;
}

export function useRewards(filters: RewardFilters) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.referrals.rewards({ ...filters }),
    queryFn: () => client.get<Page<S<"RewardRow">>>("/referrals/rewards", { ...filters }),
    placeholderData: (prev) => prev,
  });
}
