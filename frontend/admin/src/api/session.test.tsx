import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { createClient } from "./client";
import { SessionProvider, useSession } from "./session";

const admin = { id: 1, username: "root", role: "owner", totp_enabled: false, last_login_at: null };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function harness(handler: (url: string, init: RequestInit) => Response) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return handler(url, init);
  }) as unknown as typeof fetch;
  let api!: ReturnType<typeof useSession>;
  function Probe() {
    api = useSession();
    return <span>{api.status}</span>;
  }
  const client = createClient({ fetchImpl });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={new QueryClient()}>
      <SessionProvider client={client}>{children}</SessionProvider>
    </QueryClientProvider>
  );
  render(<Probe />, { wrapper });
  return { calls, get: () => api, client };
}

test("me_200_authed_sets_csrf", async () => {
  const { client, calls } = harness(() => json(200, { admin, csrf_token: "c1" }));
  await screen.findByText("authed");
  await act(async () => {
    await client.post("/x").catch(() => undefined);
  });
  expect(new Headers(calls[1].init.headers).get("X-CSRF-Token")).toBe("c1");
});

test("me_401_gives_anon", async () => {
  harness(() => json(401, { error: { code: "unauthorized", message: "no" } }));
  await screen.findByText("anon");
});

test("login_with_totp_required_error_exposes_code", async () => {
  const h = harness((url) =>
    url.endsWith("/auth/me")
      ? json(401, { error: { code: "unauthorized", message: "no" } })
      : json(401, { error: { code: "totp_required", message: "totp" } }),
  );
  await screen.findByText("anon");
  const err = await h
    .get()
    .login({ username: "root", password: "pw" })
    .catch((e: unknown) => e);
  expect(err).toMatchObject({ code: "totp_required" });
});

test("login_success_sets_admin", async () => {
  const h = harness((url) =>
    url.endsWith("/auth/me")
      ? json(401, { error: { code: "unauthorized", message: "no" } })
      : json(200, { admin, csrf_token: "c2" }),
  );
  await screen.findByText("anon");
  await act(async () => {
    await h.get().login({ username: "root", password: "pw" });
  });
  await waitFor(() => expect(h.get().status).toBe("authed"));
  expect(h.get().admin?.username).toBe("root");
});

test("logout_clears_state_and_csrf", async () => {
  const h = harness((url) =>
    url.endsWith("/auth/logout") ? new Response(null, { status: 204 }) : json(200, { admin, csrf_token: "c1" }),
  );
  await screen.findByText("authed");
  await act(async () => {
    await h.get().logout();
  });
  await waitFor(() => expect(h.get().status).toBe("anon"));
});
