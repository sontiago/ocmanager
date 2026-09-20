import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useApi } from "./ApiProvider";
import type { ApiError } from "./errors";
import { queryKeys } from "./queryKeys";
import type {
  Checkout,
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
} from "./types";

export function useMe(): UseQueryResult<Me, ApiError> {
  const api = useApi();
  return useQuery({ queryKey: queryKeys.me, queryFn: () => api.getMe() });
}

export function usePlans(): UseQueryResult<Plan[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.plans,
    queryFn: () => api.listPlans(),
    // Каталог тарифов меняется редко — незачем дёргать его при каждом фокусе.
    staleTime: 5 * 60_000,
  });
}

export function useSubscription(): UseQueryResult<
  Subscription | null,
  ApiError
> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.subscription,
    queryFn: () => api.getSubscription(),
  });
}

export function useDevices(): UseQueryResult<Device[], ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.devices,
    queryFn: () => api.listDevices(),
  });
}

export function useConnection(): UseQueryResult<ConnectionInfo, ApiError> {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.connection,
    queryFn: () => api.getConnection(),
    staleTime: Infinity,
  });
}

/** Подписка и «я» меняются вместе: trial_available и devices_used живут в разных ответах. */
function useInvalidateAccount(): () => Promise<void> {
  const qc = useQueryClient();
  return async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: queryKeys.subscription }),
      qc.invalidateQueries({ queryKey: queryKeys.me }),
      qc.invalidateQueries({ queryKey: queryKeys.devices }),
    ]);
  };
}

export function useStartTrial(): UseMutationResult<
  Subscription,
  ApiError,
  void
> {
  const api = useApi();
  const invalidate = useInvalidateAccount();
  return useMutation({
    mutationFn: () => api.startTrial(),
    onSuccess: invalidate,
  });
}

export function useCreateDevice(): UseMutationResult<
  IssuedDevice,
  ApiError,
  CreateDeviceInput
> {
  const api = useApi();
  const invalidate = useInvalidateAccount();
  return useMutation({
    mutationFn: (input: CreateDeviceInput) => api.createDevice(input),
    onSuccess: invalidate,
  });
}

export function useRevokeDevice(): UseMutationResult<void, ApiError, string> {
  const api = useApi();
  const invalidate = useInvalidateAccount();
  return useMutation({
    mutationFn: (deviceId: string) => api.revokeDevice(deviceId),
    onSuccess: invalidate,
  });
}

export function useCreateCheckout(): UseMutationResult<
  Checkout,
  ApiError,
  string
> {
  const api = useApi();
  return useMutation({
    mutationFn: (planCode: string) => api.createCheckout(planCode),
  });
}
