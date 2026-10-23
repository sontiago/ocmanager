import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiError, renderRoutes } from "../test/utils";
import { StatsPage } from "./Stats";

const day = (n: number) => `2026-10-${String(n).padStart(2, "0")}`;

const TRAFFIC = {
  days: [
    { day: day(21), bytes_in: 0, bytes_out: 0 },
    { day: day(22), bytes_in: 1024 ** 3, bytes_out: 2 * 1024 ** 3 },
  ],
  top_clients: [
    { client_id: 5, name: "Big", username: "big", bytes_in: 3 * 1024 ** 3, bytes_out: 5 * 1024 ** 3 },
    { client_id: 6, name: "Small", username: null, bytes_in: 1024 ** 2, bytes_out: 1024 ** 2 },
  ],
};
const REVENUE = {
  series: [
    { day: day(21), amounts: {} },
    { day: day(22), amounts: { RUB: 29900, USD: 500 } },
  ],
  totals: [
    { currency: "RUB", amount: 29900, count: 1, refunded_amount: 0, refunded_count: 0 },
    { currency: "USD", amount: 500, count: 1, refunded_amount: 100, refunded_count: 1 },
  ],
};
const CLIENTS = {
  series: [
    { day: day(21), count: 0 },
    { day: day(22), count: 4 },
  ],
  total: 120,
  new_in_period: 4,
  paying_in_period: 3,
};
const ECONOMICS = { mrr: { RUB: 8420000 }, arpu: { RUB: 29900 }, active_paid: 281 };

function page(over: Record<string, unknown> = {}, route = "/stats") {
  return renderRoutes(
    [
      { path: "/stats", element: <StatsPage /> },
      { path: "/clients/:id", element: <p>card</p> },
    ],
    {
      route,
      handlers: {
        "GET /admin/stats/traffic": TRAFFIC,
        "GET /admin/stats/revenue": REVENUE,
        "GET /admin/stats/clients": CLIENTS,
        "GET /admin/stats/economics": ECONOMICS,
        ...over,
      } as never,
    },
  );
}

const last = (calls: { url: URL }[], path: string) =>
  calls.filter((c) => c.url.pathname === path).at(-1)!.url.searchParams;

test("shows_kpis_from_api", async () => {
  page();
  const kpis = await screen.findByRole("region", { name: "Ключевые показатели" });
  expect(await within(kpis).findByText(/84\s?200/)).toBeInTheDocument(); // MRR
  expect(within(kpis).getByText("281")).toBeInTheDocument(); // платящих подписок
  expect(within(kpis).getByText("120")).toBeInTheDocument(); // всего клиентов
  expect(within(kpis).getByText("3")).toBeInTheDocument(); // платили за период
});

test("period_defaults_to_30_and_change_refetches_with_days", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await screen.findByRole("region", { name: "Ключевые показатели" });
  await waitFor(() => expect(last(calls, "/admin/stats/traffic").get("days")).toBe("30"));
  await user.selectOptions(screen.getByLabelText("Период"), "90");
  await waitFor(() => expect(last(calls, "/admin/stats/traffic").get("days")).toBe("90"));
  expect(last(calls, "/admin/stats/revenue").get("days")).toBe("90");
  expect(last(calls, "/admin/stats/clients").get("days")).toBe("90");
});

test("period_comes_from_url", async () => {
  const { calls } = page({}, "/stats?days=7");
  await screen.findByRole("region", { name: "Ключевые показатели" });
  await waitFor(() => expect(last(calls, "/admin/stats/traffic").get("days")).toBe("7"));
});

test("garbage_period_falls_back_to_30", async () => {
  const { calls } = page({}, "/stats?days=abc");
  await screen.findByRole("region", { name: "Ключевые показатели" });
  await waitFor(() => expect(last(calls, "/admin/stats/traffic").get("days")).toBe("30"));
});

test("revenue_totals_listed_per_currency_with_refunds", async () => {
  page();
  const totals = await screen.findByRole("region", { name: "Выручка за период" });
  expect(await within(totals).findByText(/299/)).toBeInTheDocument();
  expect(within(totals).getByText(/возвраты/i)).toBeInTheDocument();
});

test("top_clients_ranked_and_linked", async () => {
  const user = userEvent.setup();
  page();
  const table = await screen.findByRole("region", { name: "Топ клиентов по трафику" });
  const rows = await within(table).findAllByRole("row");
  expect(rows[1]).toHaveTextContent("Big");
  expect(rows[2]).toHaveTextContent("Small");
  await user.click(within(table).getByText("Big"));
  expect(await screen.findByText("card")).toBeInTheDocument();
});

test("empty_system_renders_without_errors", async () => {
  page({
    "GET /admin/stats/traffic": { days: [], top_clients: [] },
    "GET /admin/stats/revenue": { series: [], totals: [] },
    "GET /admin/stats/clients": { series: [], total: 0, new_in_period: 0, paying_in_period: 0 },
    "GET /admin/stats/economics": { mrr: {}, arpu: {}, active_paid: 0 },
  });
  const table = await screen.findByRole("region", { name: "Топ клиентов по трафику" });
  expect(await within(table).findByText("Нет данных за период")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("one_failed_request_does_not_blank_the_page", async () => {
  page({ "GET /admin/stats/revenue": apiError(500, "internal") });
  expect(await screen.findByRole("region", { name: "Ключевые показатели" })).toBeInTheDocument();
  expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
  expect(await screen.findByRole("region", { name: "Топ клиентов по трафику" })).toBeInTheDocument();
});

test("export_link_follows_the_period", async () => {
  const user = userEvent.setup();
  page();
  const link = await screen.findByRole("link", { name: "Экспорт CSV" });
  expect(link).toHaveAttribute("href", "/admin/export/traffic.csv?days=30");
  await user.selectOptions(screen.getByLabelText("Период"), "90");
  await waitFor(() =>
    expect(screen.getByRole("link", { name: "Экспорт CSV" })).toHaveAttribute(
      "href",
      "/admin/export/traffic.csv?days=90",
    ),
  );
});
