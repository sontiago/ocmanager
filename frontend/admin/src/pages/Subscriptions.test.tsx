import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoutes } from "../test/utils";
import { SubscriptionsPage } from "./Subscriptions";

const ROW = {
  client_id: 5,
  telegram_id: 777,
  username: "bob",
  first_name: "Bob",
  status: "active",
  plan_code: "pro",
  plan_is_trial: false,
  started_at: "2026-10-01T00:00:00Z",
  expires_at: "2026-11-01T00:00:00Z",
  auto_renew: true,
  traffic_used_bytes: 0,
  traffic_limit_bytes: null,
};

function page(route = "/subscriptions") {
  return renderRoutes([{ path: "/subscriptions", element: <SubscriptionsPage /> }], {
    route,
    handlers: {
      "GET /admin/subscriptions": { items: [ROW], total: 1, limit: 50, offset: 0 },
      "GET /admin/plans": [],
      "POST /admin/subscriptions/5/expire": { changed: true },
      "POST /admin/subscriptions/5/cancel-auto-renew": { changed: true },
    },
  });
}

test("reads_filters_from_url", async () => {
  const { calls } = page("/subscriptions?status=active&expiring_within_days=3");
  await screen.findByText(/Bob/);
  const q = calls.find((c) => c.url.pathname === "/admin/subscriptions")!.url.searchParams;
  expect(q.get("status")).toBe("active");
  expect(q.get("expiring_within_days")).toBe("3");
});

test("expire_requires_confirmation", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await user.click(await screen.findByRole("button", { name: "Закрыть доступ" }));
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Закрыть доступ" }));
  await waitFor(() =>
    expect(calls.some((c) => c.url.pathname === "/admin/subscriptions/5/expire")).toBe(true),
  );
});

test("cancel_auto_renew_posts", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await user.click(await screen.findByRole("button", { name: "Отключить автопродление" }));
  await waitFor(() =>
    expect(calls.some((c) => c.url.pathname === "/admin/subscriptions/5/cancel-auto-renew")).toBe(true),
  );
});

test("export_link_carries_current_filters", async () => {
  page("/subscriptions?status=active&expiring_within_days=3");
  const link = await screen.findByRole("link", { name: "Экспорт CSV" });
  expect(link).toHaveAttribute(
    "href",
    "/admin/export/subscriptions.csv?status=active&expiring_within_days=3",
  );
});
