import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiError, renderRoutes } from "../test/utils";
import { ClientDetailPage } from "./ClientDetail";

const DEVICE = {
  id: 11,
  client_id: 5,
  seq: 1,
  name: "iPhone",
  platform: "ios",
  username: "c5-d1",
  issued_at: "2026-10-01T00:00:00Z",
  cert_expires_at: "2027-10-01T00:00:00Z",
  revoked_at: null,
  revocation_reason: null,
  last_seen_at: null,
  is_online: null,
  traffic_bytes: 0,
};

function card(over: Record<string, unknown> = {}) {
  return {
    client: {
      id: 5,
      telegram_id: 777,
      username: "bob",
      first_name: "Bob",
      lang: "ru",
      is_blocked: false,
      trial_used_at: null,
      created_at: "2026-10-01T00:00:00Z",
    },
    subscription: {
      status: "active",
      plan_code: "pro",
      plan_name_i18n: { ru: "Про", en: "Pro" },
      plan_is_trial: false,
      started_at: "2026-10-01T00:00:00Z",
      expires_at: "2026-11-01T00:00:00Z",
      auto_renew: true,
      device_limit: 1,
      devices_active: 2,
      over_device_limit: true,
      traffic_limit_bytes: null,
      traffic_used_bytes: 0,
      traffic_period_start: "2026-10-01T00:00:00Z",
      provider: "tribute",
    },
    devices: [DEVICE],
    traffic_daily: [],
    sessions: [],
    payments: [],
    referral: {
      code: "ab23cd45",
      referred_by: null,
      invited: 0,
      paying_friends: 0,
      bonus_devices: 0,
      bonus_traffic_bytes: 0,
    },
    ...over,
  };
}

const PLANS = [
  { id: 1, code: "pro", name_i18n: { ru: "Про", en: "Pro" }, is_active: true, is_trial: false },
];

function page(over: Record<string, unknown> = {}, extra: Record<string, never | object> = {}) {
  return renderRoutes([{ path: "/clients/:id", element: <ClientDetailPage /> }], {
    route: "/clients/5",
    handlers: {
      "GET /admin/clients/5": card(over),
      "GET /admin/plans": PLANS,
      ...extra,
    },
  });
}

const posts = (calls: { method: string; url: URL; body: unknown }[], path: string) =>
  calls.filter((c) => c.method === "POST" && c.url.pathname === path);

test("over_device_limit_is_flagged", async () => {
  page();
  expect(await screen.findByText(/превышен лимит устройств/i)).toBeInTheDocument();
});

test("block_requires_confirmation", async () => {
  const user = userEvent.setup();
  const { calls } = page({}, { "POST /admin/clients/5/block": { changed: true } });
  await user.click(await screen.findByRole("button", { name: "Заблокировать" }));
  expect(posts(calls, "/admin/clients/5/block")).toHaveLength(0);
  const dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Заблокировать" }));
  await waitFor(() => expect(posts(calls, "/admin/clients/5/block")).toHaveLength(1));
});

test("unchanged_action_shows_no_change_notice", async () => {
  const user = userEvent.setup();
  page(
    { client: { ...card().client, is_blocked: true } },
    { "POST /admin/clients/5/unblock": { changed: false } },
  );
  await user.click(await screen.findByRole("button", { name: "Разблокировать" }));
  expect(await screen.findByText("Изменений нет")).toBeInTheDocument();
});

test("grant_sends_plan_code_and_days", async () => {
  const user = userEvent.setup();
  const { calls } = page({}, { "POST /admin/clients/5/grant": { changed: true } });
  await user.click(await screen.findByRole("button", { name: "Выдать подписку" }));
  const dialog = await screen.findByRole("dialog");
  await user.selectOptions(await within(dialog).findByLabelText("Тариф"), "pro");
  await user.type(within(dialog).getByLabelText("Дней (необязательно)"), "30");
  await user.click(within(dialog).getByRole("button", { name: "Выдать" }));
  await waitFor(() => expect(posts(calls, "/admin/clients/5/grant")).toHaveLength(1));
  expect(posts(calls, "/admin/clients/5/grant")[0].body).toEqual({ plan_code: "pro", days: 30 });
});

test("grant_without_days_omits_days", async () => {
  const user = userEvent.setup();
  const { calls } = page({}, { "POST /admin/clients/5/grant": { changed: true } });
  await user.click(await screen.findByRole("button", { name: "Выдать подписку" }));
  const dialog = await screen.findByRole("dialog");
  await user.selectOptions(await within(dialog).findByLabelText("Тариф"), "pro");
  await user.click(within(dialog).getByRole("button", { name: "Выдать" }));
  await waitFor(() => expect(posts(calls, "/admin/clients/5/grant")).toHaveLength(1));
  expect(posts(calls, "/admin/clients/5/grant")[0].body).toEqual({ plan_code: "pro" });
});

test("extend_sends_days", async () => {
  const user = userEvent.setup();
  const { calls } = page({}, { "POST /admin/clients/5/extend": { changed: true } });
  await user.click(await screen.findByRole("button", { name: "Продлить" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Дней"), "7");
  await user.click(within(dialog).getByRole("button", { name: "Продлить" }));
  await waitFor(() => expect(posts(calls, "/admin/clients/5/extend")).toHaveLength(1));
  expect(posts(calls, "/admin/clients/5/extend")[0].body).toEqual({ days: 7 });
});

test("issue_device_shows_password_once_and_clears_on_close", async () => {
  const user = userEvent.setup();
  const { queryClient, calls } = page(
    {},
    {
      "POST /admin/clients/5/devices": {
        device: DEVICE,
        p12_password: "s3cret-pass",
        download_path: "/admin/downloads/tok",
        download_expires_at: "2026-10-23T12:00:00Z",
      },
    },
  );
  await user.click(await screen.findByRole("button", { name: "Выпустить устройство" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Название"), "Pixel");
  await user.selectOptions(within(dialog).getByLabelText("Платформа"), "android");
  await user.click(within(dialog).getByRole("button", { name: "Выпустить" }));
  expect(await screen.findByText("s3cret-pass")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Скачать/ })).toHaveAttribute("href", "/admin/downloads/tok");
  expect(posts(calls, "/admin/clients/5/devices")[0].body).toEqual({ name: "Pixel", platform: "android" });

  await user.click(screen.getByRole("button", { name: "Закрыть" }));
  expect(screen.queryByText("s3cret-pass")).toBeNull();
  await waitFor(() => {
    const held = queryClient
      .getMutationCache()
      .getAll()
      .filter((m) => JSON.stringify(m.state.data ?? "").includes("s3cret-pass"));
    expect(held).toHaveLength(0);
  });
});

test("block_failure_is_shown_to_the_operator", async () => {
  const user = userEvent.setup();
  page({}, { "POST /admin/clients/5/block": apiError(409, "conflict", "already processing") });
  await user.click(await screen.findByRole("button", { name: "Заблокировать" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Заблокировать" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already processing");
});

test("issue_dialog_cannot_be_closed_while_request_is_pending", async () => {
  const user = userEvent.setup();
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  page(
    {},
    {
      "POST /admin/clients/5/devices": () => gate.then(() => undefined),
    },
  );
  await user.click(await screen.findByRole("button", { name: "Выпустить устройство" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Название"), "Pixel");
  await user.click(within(dialog).getByRole("button", { name: "Выпустить" }));
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "Отмена" })).toBeDisabled());
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  release();
});

function withSub(over: Record<string, unknown>) {
  return { subscription: { ...(card().subscription as object), ...over } };
}

test("quota_progress_shows_used_share_of_the_limit", async () => {
  page(withSub({ traffic_limit_bytes: 1000, traffic_used_bytes: 250 }));
  const bar = await screen.findByRole("progressbar", { name: "Трафик периода" });
  expect(bar).toHaveAttribute("aria-valuenow", "25");
});

test("quota_progress_is_capped_at_100", async () => {
  page(withSub({ traffic_limit_bytes: 1000, traffic_used_bytes: 5000 }));
  expect(await screen.findByRole("progressbar", { name: "Трафик периода" })).toHaveAttribute(
    "aria-valuenow",
    "100",
  );
});

test("unlimited_plan_has_no_progress_bar", async () => {
  page(withSub({ traffic_limit_bytes: null, traffic_used_bytes: 5000 }));
  await screen.findByText("Профиль");
  expect(screen.queryByRole("progressbar")).toBeNull();
});

test("exhausted_subscription_is_called_out", async () => {
  page(withSub({ status: "exhausted", traffic_limit_bytes: 1000, traffic_used_bytes: 1000 }));
  expect(await screen.findByText("Квота трафика исчерпана: доступ закрыт")).toBeInTheDocument();
});

test("reset_traffic_asks_confirmation_then_posts", async () => {
  const user = userEvent.setup();
  const { calls } = page(
    withSub({ status: "exhausted", traffic_limit_bytes: 1000, traffic_used_bytes: 1000 }),
    { "POST /admin/clients/5/reset-traffic": { changed: true } },
  );
  await user.click(await screen.findByRole("button", { name: "Сбросить трафик" }));
  expect(posts(calls, "/admin/clients/5/reset-traffic")).toHaveLength(0);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Сбросить" }));
  await waitFor(() => expect(posts(calls, "/admin/clients/5/reset-traffic")).toHaveLength(1));
  expect(await screen.findByText("Готово")).toBeInTheDocument();
});

test("reset_traffic_is_hidden_without_a_subscription", async () => {
  page({ subscription: null });
  await screen.findByText("Профиль");
  expect(screen.queryByRole("button", { name: "Сбросить трафик" })).toBeNull();
});


test("referral_block_shows_the_code_and_counts", async () => {
  page({
    referral: {
      code: "ab23cd45",
      referred_by: null,
      invited: 5,
      paying_friends: 3,
      bonus_devices: 1,
      bonus_traffic_bytes: 100 * 1024 ** 3,
    },
  });
  const block = await screen.findByRole("region", { name: "Рефералы" });
  expect(within(block).getByText("ab23cd45")).toBeInTheDocument();
  expect(within(block).getByText("5")).toBeInTheDocument();
  expect(within(block).getByText("3")).toBeInTheDocument();
  expect(within(block).getByText(/\+1/)).toBeInTheDocument();
  expect(within(block).getByRole("link", { name: /Награды/ })).toHaveAttribute(
    "href",
    "/referrals?inviter_id=5",
  );
});

test("referral_block_links_to_the_inviter", async () => {
  page({
    referral: {
      code: "ab23cd45",
      referred_by: { id: 9, name: "Ivan" },
      invited: 0,
      paying_friends: 0,
      bonus_devices: 0,
      bonus_traffic_bytes: 0,
    },
  });
  const block = await screen.findByRole("region", { name: "Рефералы" });
  expect(within(block).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/clients/9");
});
