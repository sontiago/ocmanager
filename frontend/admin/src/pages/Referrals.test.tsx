import { screen, within } from "@testing-library/react";
import { renderRoutes } from "../test/utils";
import { ReferralsPage } from "./Referrals";

const STATS = {
  invited: 40,
  paying: 10,
  conversion_percent: 25,
  days_given: 120,
  devices_given: 2,
  traffic_bytes_given: 100 * 1024 ** 3,
  tiers: [
    { friends: 3, reached: 4 },
    { friends: 5, reached: 2 },
    { friends: 10, reached: 0 },
  ],
};

const reward = (over: Record<string, unknown> = {}) => ({
  id: 1,
  created_at: "2026-10-20T10:00:00Z",
  inviter_id: 5,
  inviter_name: "Ivan",
  invitee_id: 6,
  invitee_name: "Petr",
  kind: "base",
  tier: null,
  days: 7,
  invitee_days: 3,
  devices: 0,
  traffic_bytes: 0,
  status: "applied",
  payment_id: 9,
  payment_status: "succeeded",
  ...over,
});

function page(items: object[] = [reward()], route = "/referrals") {
  return renderRoutes([{ path: "/referrals", element: <ReferralsPage /> }], {
    route,
    handlers: {
      "GET /admin/referrals/stats": STATS,
      "GET /admin/referrals/rewards": { items, total: items.length, limit: 50, offset: 0 },
    },
  });
}

test("shows_the_funnel_numbers", async () => {
  page();
  const kpis = await screen.findByRole("region", { name: "Итоги программы" });
  expect(within(kpis).getByText("40")).toBeInTheDocument();
  expect(within(kpis).getByText("10")).toBeInTheDocument();
  expect(within(kpis).getByText("25%")).toBeInTheDocument();
  expect(within(kpis).getByText("120")).toBeInTheDocument();
});

test("shows_how_many_reached_each_tier", async () => {
  page();
  const tiers = await screen.findByRole("region", { name: "Уровни" });
  expect(within(tiers).getByText(/Уровень 3/)).toBeInTheDocument();
  expect(within(tiers).getByText("4")).toBeInTheDocument();
  expect(within(tiers).getByText("2")).toBeInTheDocument();
});

test("the_log_names_people_and_links_to_them", async () => {
  page();
  const link = await screen.findByRole("link", { name: "Ivan" });
  expect(link).toHaveAttribute("href", "/clients/5");
  expect(screen.getByRole("link", { name: "Petr" })).toHaveAttribute("href", "/clients/6");
});

test("a_reward_for_a_refunded_payment_is_flagged", async () => {
  page([reward({ payment_status: "refunded" })]);
  expect(await screen.findByText("платёж возвращён")).toBeInTheDocument();
});

test("a_normal_reward_is_not_flagged", async () => {
  page();
  await screen.findByRole("link", { name: "Ivan" });
  expect(screen.queryByText("платёж возвращён")).toBeNull();
});

test("pending_and_capped_rewards_are_labelled", async () => {
  page([reward({ id: 2, status: "pending" }), reward({ id: 3, status: "capped", days: 0 })]);
  expect(await screen.findByText("ждёт подписку")).toBeInTheDocument();
  expect(screen.getByText("лимит месяца")).toBeInTheDocument();
});

test("tier_rows_show_what_was_given", async () => {
  page([reward({ kind: "tier", tier: 5, days: 0, devices: 1, invitee_days: 0 })]);
  const log = await screen.findByRole("region", { name: "Журнал наград" });
  expect(await within(log).findByText("Уровень 5")).toBeInTheDocument();
  expect(within(log).getByText("+1 устройство")).toBeInTheDocument();
});

test("the_empty_log_says_so", async () => {
  page([]);
  expect(await screen.findByText("Наград пока нет")).toBeInTheDocument();
});

test("filtering_by_inviter_comes_from_the_url", async () => {
  const { calls } = page([reward()], "/referrals?inviter_id=5");
  await screen.findByRole("link", { name: "Ivan" });
  const q = calls.find((c) => c.url.pathname === "/admin/referrals/rewards")!.url.searchParams;
  expect(q.get("inviter_id")).toBe("5");
});
