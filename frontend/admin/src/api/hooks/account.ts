import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { S } from "../types";
import { useApiMutation } from "./mutate";

export const useChangePassword = () =>
  useApiMutation<S<"PasswordBody">, void>((c, body) => c.post("/auth/password", body), []);

export const useTotpSetup = () =>
  useApiMutation<void, S<"TotpSetupOut">>((c) => c.post("/auth/totp/setup"), [], { gcTime: 0 });

export const useTotpConfirm = () =>
  useApiMutation<string, void>((c, code) => c.post("/auth/totp/confirm", { code }), []);

export const useTotpDisable = () =>
  useApiMutation<string, void>((c, code) => c.post("/auth/totp/disable", { code }), []);

export function useAdminSessions() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.adminSessions,
    queryFn: () => client.get<S<"SessionOut">[]>("/auth/sessions"),
  });
}

export const useCloseSession = () =>
  useApiMutation<number, void>((c, id) => c.delete(`/auth/sessions/${id}`), [
    queryKeys.adminSessions,
  ]);
