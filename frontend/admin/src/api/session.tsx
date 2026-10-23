import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { ApiClient } from "./client";
import type { S } from "./types";

export type SessionStatus = "loading" | "anon" | "authed";

export interface SessionValue {
  admin: S<"AdminOut"> | null;
  status: SessionStatus;
  login(body: S<"LoginBody">): Promise<void>;
  logout(): Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);
const ClientContext = createContext<ApiClient | null>(null);

export function useApiClient(): ApiClient {
  const client = useContext(ClientContext);
  if (!client) throw new Error("ApiClient не предоставлен: оберните в SessionProvider");
  return client;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("SessionProvider не найден");
  return value;
}

export function SessionProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  const queryClient = useQueryClient();
  const [admin, setAdmin] = useState<S<"AdminOut"> | null>(null);
  const [status, setStatus] = useState<SessionStatus>("loading");

  const reset = useCallback(() => {
    client.setCsrf(null);
    setAdmin(null);
    setStatus("anon");
    queryClient.clear();
  }, [client, queryClient]);

  const accept = useCallback(
    (auth: S<"AuthOut">) => {
      client.setCsrf(auth.csrf_token);
      setAdmin(auth.admin);
      setStatus("authed");
    },
    [client],
  );

  useEffect(() => {
    client.setOnUnauthorized(reset);
    let alive = true;
    client
      .get<S<"AuthOut">>("/auth/me")
      .then((auth) => alive && accept(auth))
      .catch(() => alive && reset());
    return () => {
      alive = false;
      client.setOnUnauthorized(undefined);
    };
  }, [client, accept, reset]);

  const login = useCallback(
    async (body: S<"LoginBody">) => {
      accept(await client.post<S<"AuthOut">>("/auth/login", body));
    },
    [client, accept],
  );

  const logout = useCallback(async () => {
    try {
      await client.post("/auth/logout");
    } finally {
      reset();
    }
  }, [client, reset]);

  const value = useMemo(
    () => ({ admin, status, login, logout }),
    [admin, status, login, logout],
  );
  return (
    <ClientContext.Provider value={client}>
      <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
    </ClientContext.Provider>
  );
}
