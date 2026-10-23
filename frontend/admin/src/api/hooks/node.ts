import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import { useApiClient } from "../session";
import type { S } from "../types";
import { useApiMutation } from "./mutate";

export type NodeAction = "reload" | "start" | "stop" | "restart" | "disconnect_user";

export function useNode() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.node.status,
    queryFn: () => client.get<S<"NodeStatusOut">>("/node"),
    refetchInterval: 10_000,
  });
}

export function useNodeSessions() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.node.sessions,
    queryFn: () => client.get<S<"LiveSessionOut">[]>("/node/sessions"),
    refetchInterval: 10_000,
    retry: false,
  });
}

export const useNodeProbe = () =>
  useApiMutation<void, S<"HealthOut">>((c) => c.post("/node/probe"), [
    queryKeys.node.all,
    queryKeys.overview,
  ]);

export const useNodeAction = () =>
  useApiMutation<{ action: NodeAction; username?: string }, void>(
    (c, body) => c.post("/node/actions", body),
    [queryKeys.node.all, queryKeys.overview],
  );

export const useReconcile = () =>
  useApiMutation<void, S<"ReconcileOut">>((c) => c.post("/node/reconcile"), [
    queryKeys.node.all,
    queryKeys.overview,
  ]);
