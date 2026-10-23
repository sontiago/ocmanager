import { screen, within } from "@testing-library/react";
import { apiError, renderPage } from "../test/utils";
import { OverviewPage } from "./Overview";

const NODE = {
  id: 1,
  name: "node-1",
  driver: "local",
  public_host: "vpn.example.com",
  status: "online",
  last_seen_at: "2026-10-23T10:00:00Z",
  is_active: true,
  last_reconcile_at: "2026-10-23T10:00:00Z",
};

const FULL = {
  node: NODE,
  health: {
    state: "online",
    container_state: "running",
    active_sessions: 128,
    checked_at: "2026-10-23T10:00:00Z",
    error: null,
  },
  active_sessions: 128,
  traffic: { from_day: "2026-10-22", to_day: "2026-10-23", bytes_in: 1024 ** 3, bytes_out: 3 * 1024 ** 3 },
  subscriptions_by_status: { active: 310, trial: 42, expired: 90 },
  expiring_soon: 17,
  recent_audit: [
    {
      id: 1,
      created_at: "2026-10-23T09:00:00Z",
      actor_type: "admin",
      actor_id: "1",
      ip: null,
      action: "client.block",
      target_type: "client",
      target_id: "5",
      details: {},
    },
  ],
  last_reconcile: null,
  revenue: { RUB: 8420000, USD: 1500 },
  recent_payments: [
    {
      id: 9,
      client_id: 5,
      subscription_id: 1,
      provider: "tribute",
      external_id: "x1",
      plan_id: 1,
      amount: 29900,
      currency: "RUB",
      status: "succeeded",
      received_at: "2026-10-23T08:00:00Z",
      processed_at: "2026-10-23T08:00:01Z",
    },
  ],
  webhooks_needing_attention: 0,
};

const EMPTY = {
  node: null,
  health: null,
  active_sessions: null,
  traffic: { from_day: "2026-10-22", to_day: "2026-10-23", bytes_in: 0, bytes_out: 0 },
  subscriptions_by_status: { active: 0, trial: 0, expired: 0 },
  expiring_soon: 0,
  recent_audit: [],
  last_reconcile: null,
  revenue: {},
  recent_payments: [],
  webhooks_needing_attention: 0,
};

function page(data: unknown) {
  return renderPage(
    <OverviewPage />,
    { handlers: { "GET /admin/overview": data as object } },
  );
}

test("renders_both_columns_with_data", async () => {
  page(FULL);
  const service = await screen.findByRole("region", { name: "Сервис" });
  const money = screen.getByRole("region", { name: "Деньги" });
  expect(within(service).getByText("128")).toBeInTheDocument();
  expect(within(service).getByText("client.block")).toBeInTheDocument();
  expect(within(money).getByText("17")).toBeInTheDocument();
  expect(within(money).getByText("310")).toBeInTheDocument();
});

test("multi_currency_revenue_listed_per_currency", async () => {
  page(FULL);
  const money = await screen.findByRole("region", { name: "Деньги" });
  expect(within(money).getByText(/84\s?200/)).toBeInTheDocument();
  expect(within(money).getByText(/15/)).toBeInTheDocument();
});

test("empty_database_renders_zeros_without_error", async () => {
  page(EMPTY);
  const service = await screen.findByRole("region", { name: "Сервис" });
  expect(within(service).getByText("Ноды ещё нет")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("null_health_shows_no_data_not_offline", async () => {
  page({ ...FULL, health: null, active_sessions: null });
  const service = await screen.findByRole("region", { name: "Сервис" });
  expect(within(service).getAllByText("нет данных").length).toBeGreaterThan(0);
  expect(within(service).queryByText(/offline/i)).toBeNull();
});

test("warns_when_webhooks_need_attention", async () => {
  page({ ...FULL, webhooks_needing_attention: 3 });
  const link = await screen.findByRole("link", { name: /вебхуков требуют внимания: 3/i });
  expect(link).toHaveAttribute("href", "/payments?tab=webhooks");
});

test("status_links_filter_subscriptions", async () => {
  page(FULL);
  const link = await screen.findByRole("link", { name: /активна/ });
  expect(link).toHaveAttribute("href", "/subscriptions?status=active");
});

test("shows_error_state_on_api_failure", async () => {
  renderPage(
    <OverviewPage />,
    { handlers: { "GET /admin/overview": apiError(500, "internal") } },
  );
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});

test("subscription_statuses_are_shown_in_the_interface_language", async () => {
  page({
    ...FULL,
    subscriptions_by_status: { pending_payment: 0, active: 310, exhausted: 4, trial: 42 },
  });
  const money = await screen.findByRole("region", { name: "Деньги" });
  expect(within(money).getByText("активна")).toBeInTheDocument();
  expect(within(money).getByText("трафик исчерпан")).toBeInTheDocument();
  expect(within(money).getByText("ждёт оплаты")).toBeInTheDocument();
  expect(within(money).queryByText("pending_payment")).toBeNull();
});

test("the_dynamics_card_shows_a_week_and_links_to_statistics", async () => {
  renderPage(<OverviewPage />, {
    handlers: {
      "GET /admin/overview": FULL,
      "GET /admin/stats/traffic": {
        days: [
          { day: "2026-10-22", bytes_in: 10, bytes_out: 20 },
          { day: "2026-10-23", bytes_in: 30, bytes_out: 40 },
        ],
        top_clients: [],
      },
    },
  });
  const card = await screen.findByRole("region", { name: "Динамика" });
  expect(within(card).getByRole("link", { name: /Подробная статистика/ })).toHaveAttribute(
    "href",
    "/stats",
  );
});

test("the_dynamics_card_asked_for_seven_days", async () => {
  const { calls } = renderPage(<OverviewPage />, {
    handlers: {
      "GET /admin/overview": FULL,
      "GET /admin/stats/traffic": { days: [], top_clients: [] },
    },
  });
  await screen.findByRole("region", { name: "Динамика" });
  const q = calls.find((c) => c.url.pathname === "/admin/stats/traffic")!.url.searchParams;
  expect(q.get("days")).toBe("7");
});

test("a_failed_dynamics_request_hides_the_card_without_breaking_the_page", async () => {
  renderPage(<OverviewPage />, {
    handlers: {
      "GET /admin/overview": FULL,
      "GET /admin/stats/traffic": apiError(500, "internal"),
    },
  });
  await screen.findByRole("region", { name: "Сервис" });
  expect(screen.queryByRole("region", { name: "Динамика" })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});
