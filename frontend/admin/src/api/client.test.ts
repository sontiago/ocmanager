import { ApiError } from "./errors";
import { createClient } from "./client";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function setup(res: Response | (() => Promise<Response>), onUnauthorized = vi.fn()) {
  const fetchImpl = vi.fn<typeof fetch>(typeof res === "function" ? res : async () => res.clone());
  const client = createClient({ fetchImpl, onUnauthorized });
  return { client, fetchImpl, onUnauthorized };
}

function headersOf(fetchImpl: ReturnType<typeof setup>["fetchImpl"], call = 0): Headers {
  return new Headers(fetchImpl.mock.calls[call][1]?.headers);
}

test("adds_csrf_on_post_not_on_get", async () => {
  const { client, fetchImpl } = setup(json(200, {}));
  client.setCsrf("tok");
  await client.get("/clients");
  await client.post("/clients/1/block");
  const get = headersOf(fetchImpl, 0);
  const post = headersOf(fetchImpl, 1);
  expect(get.get("X-CSRF-Token")).toBeNull();
  expect(post.get("X-CSRF-Token")).toBe("tok");
});

test("prefixes_admin_and_sends_json_body", async () => {
  const { client, fetchImpl } = setup(json(200, {}));
  await client.patch("/plans/pro", { price_amount: 5 });
  const [url, init] = fetchImpl.mock.calls[0];
  expect(url).toBe("/admin/plans/pro");
  expect(init?.method).toBe("PATCH");
  expect(init?.body).toBe('{"price_amount":5}');
  expect(headersOf(fetchImpl).get("Content-Type")).toBe("application/json");
});

test("parses_error_envelope_into_ApiError", async () => {
  const { client } = setup(json(409, { error: { code: "conflict", message: "x" } }));
  const err = await client.post("/x").catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ code: "conflict", status: 409, message: "x" });
});

test("non_json_error_body_gives_code_http_status", async () => {
  const { client } = setup(new Response("<html>bad gateway</html>", { status: 502 }));
  const err = await client.get("/x").catch((e) => e);
  expect(err).toMatchObject({ code: "http_502", status: 502 });
});

test("401_calls_onUnauthorized_once", async () => {
  const { client, onUnauthorized } = setup(
    json(401, { error: { code: "unauthorized", message: "no" } }),
  );
  await client.get("/x").catch(() => undefined);
  expect(onUnauthorized).toHaveBeenCalledTimes(1);
});

test("undefined_query_values_are_dropped", async () => {
  const { client, fetchImpl } = setup(json(200, {}));
  await client.get("/clients", { q: "bob", status: undefined, blocked: false, limit: 50 });
  expect(fetchImpl.mock.calls[0][0]).toBe("/admin/clients?q=bob&blocked=false&limit=50");
});

test("204_returns_undefined", async () => {
  const { client } = setup(new Response(null, { status: 204 }));
  expect(await client.post("/auth/logout")).toBeUndefined();
});

test("network_failure_is_ApiError_network", async () => {
  const { client } = setup(() => Promise.reject(new TypeError("fail")));
  const err = await client.get("/x").catch((e) => e);
  expect(err).toMatchObject({ code: "network", status: 0 });
});
