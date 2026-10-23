import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoutes } from "../test/utils";
import { ClientsPage } from "./Clients";

const ROW = {
  id: 5,
  telegram_id: 777,
  username: "bob",
  first_name: "Bob",
  lang: "ru",
  is_blocked: false,
  trial_used_at: null,
  created_at: "2026-10-01T00:00:00Z",
  subscription_status: "active",
  plan_code: "pro",
  expires_at: "2026-11-01T00:00:00Z",
  devices_active: 2,
};

function page(route = "/clients") {
  const list = vi.fn(() => ({ items: [ROW], total: 120, limit: 50, offset: 0 }));
  const utils = renderRoutes(
    [
      { path: "/clients", element: <ClientsPage /> },
      { path: "/clients/:id", element: <p>card</p> },
    ],
    { route, handlers: { "GET /admin/clients": list } },
  );
  return { ...utils, list };
}

const lastQuery = (calls: { url: URL; method: string }[]) =>
  calls.filter((c) => c.url.pathname === "/admin/clients").at(-1)!.url.searchParams;

test("lists_clients_and_opens_card", async () => {
  const user = userEvent.setup();
  page();
  await user.click(await screen.findByText("Bob"));
  expect(await screen.findByText("card")).toBeInTheDocument();
});

test("search_is_debounced_and_sent_as_q", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await screen.findByText("Bob");
  await user.type(screen.getByPlaceholderText("Поиск по имени, @username или Telegram ID"), "bob");
  await waitFor(() => expect(lastQuery(calls).get("q")).toBe("bob"), { timeout: 2000 });
  const withQ = calls.filter((c) => c.url.searchParams.get("q"));
  expect(withQ.every((c) => c.url.searchParams.get("q") === "bob")).toBe(true);
});

test("filter_change_resets_offset", async () => {
  const user = userEvent.setup();
  const { calls } = page("/clients?offset=50");
  await screen.findByText("Bob");
  expect(lastQuery(calls).get("offset")).toBe("50");
  await user.selectOptions(screen.getByLabelText("Статус"), "active");
  await waitFor(() => expect(lastQuery(calls).get("status")).toBe("active"));
  expect(lastQuery(calls).get("offset")).toBe("0");
});

test("blocked_filter_is_sent_as_boolean", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await screen.findByText("Bob");
  await user.selectOptions(screen.getByLabelText("Блокировка"), "true");
  await waitFor(() => expect(lastQuery(calls).get("blocked")).toBe("true"));
});
