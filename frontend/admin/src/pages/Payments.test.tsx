import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoutes } from "../test/utils";
import { PaymentsPage } from "./Payments";

const PAYMENT = {
  id: 9,
  client_id: 5,
  subscription_id: 1,
  provider: "tribute",
  external_id: "ext-1",
  plan_id: 1,
  amount: 29900,
  currency: "RUB",
  status: "succeeded",
  received_at: "2026-10-23T08:00:00Z",
  processed_at: null,
};

const hook = (over: Record<string, unknown> = {}) => ({
  id: 3,
  provider: "tribute",
  external_event_id: "evt-3",
  signature_ok: true,
  status: "failed",
  attempts: 2,
  last_error: "boom",
  received_at: "2026-10-23T08:00:00Z",
  processed_at: null,
  ...over,
});

function page(route: string, webhooks: unknown[] = [hook()]) {
  return renderRoutes([{ path: "/payments", element: <PaymentsPage /> }], {
    route,
    handlers: {
      "GET /admin/payments": { items: [PAYMENT], total: 1, limit: 50, offset: 0 },
      "GET /admin/webhooks": { items: webhooks, total: webhooks.length, limit: 50, offset: 0 },
      "GET /admin/webhooks/3": { ...hook(), payload: { amount: 1 } },
      "POST /admin/webhooks/3/reprocess": hook({ status: "received" }),
    },
  });
}

const last = (calls: { url: URL }[], path: string) =>
  calls.filter((c) => c.url.pathname === path).at(-1)!.url.searchParams;

test("unprocessed_payment_is_flagged", async () => {
  page("/payments");
  expect(await screen.findByText("доступ не выдан")).toBeInTheDocument();
});

test("since_until_sent_as_utc_iso", async () => {
  const user = userEvent.setup();
  const { calls } = page("/payments");
  await screen.findByText("доступ не выдан");
  await user.type(screen.getByLabelText("С даты"), "2026-10-01");
  await user.type(screen.getByLabelText("По дату"), "2026-10-02");
  await waitFor(() => expect(last(calls, "/admin/payments").get("until")).not.toBeNull());
  const q = last(calls, "/admin/payments");
  expect(q.get("since")).toBe("2026-10-01T00:00:00.000Z");
  // «по дату» включительно: бэкенд сравнивает `< until`, поэтому уходит начало следующих суток
  expect(q.get("until")).toBe("2026-10-03T00:00:00.000Z");
});

test("default_webhook_tab_lists_needing_attention", async () => {
  page("/payments?tab=webhooks");
  expect(await screen.findByText("evt-3")).toBeInTheDocument();
});

test("webhooks_default_sends_no_status", async () => {
  const { calls } = page("/payments?tab=webhooks");
  await screen.findByText("evt-3");
  expect(last(calls, "/admin/webhooks").get("status")).toBeNull();
});

test("status_all_sends_status_all", async () => {
  const user = userEvent.setup();
  const { calls } = page("/payments?tab=webhooks");
  await screen.findByText("evt-3");
  await user.selectOptions(screen.getByLabelText("Статус"), "all");
  await waitFor(() => expect(last(calls, "/admin/webhooks").get("status")).toBe("all"));
});

test("reprocess_posts_for_failed_webhook", async () => {
  const user = userEvent.setup();
  const { calls } = page("/payments?tab=webhooks");
  await user.click(await screen.findByRole("button", { name: "Переобработать" }));
  await waitFor(() =>
    expect(calls.some((c) => c.url.pathname === "/admin/webhooks/3/reprocess")).toBe(true),
  );
});

test("reprocess_hidden_for_processed_webhook", async () => {
  page("/payments?tab=webhooks", [hook({ status: "processed" })]);
  await screen.findByText("evt-3");
  expect(screen.queryByRole("button", { name: "Переобработать" })).toBeNull();
});

test("webhook_detail_shows_payload", async () => {
  const user = userEvent.setup();
  page("/payments?tab=webhooks");
  await user.click(await screen.findByRole("button", { name: "Подробнее" }));
  expect(await screen.findByText(/"amount": 1/)).toBeInTheDocument();
});
