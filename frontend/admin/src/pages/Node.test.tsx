import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FakeEventSource } from "../test/FakeEventSource";
import { renderRoutes } from "../test/utils";
import { NodePage } from "./Node";

beforeEach(() => {
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => vi.unstubAllGlobals());

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
const HEALTH = {
  state: "online",
  container_state: "running",
  active_sessions: 1,
  checked_at: "2026-10-23T10:00:00Z",
  error: null,
};
const SESSION = {
  session_id: "s1",
  username: "c5-d1",
  remote_ip: "1.2.3.4",
  vpn_ip: "10.0.0.2",
  bytes_in: 1024,
  bytes_out: 2048,
  connected_at: "2026-10-23T09:00:00Z",
  user_agent: null,
  device_id: 11,
  device_name: "iPhone",
  client_id: 5,
  telegram_id: 777,
  client_name: "Bob",
};

function page(health: unknown = HEALTH) {
  return renderRoutes([{ path: "/node", element: <NodePage /> }], {
    route: "/node",
    handlers: {
      "GET /admin/node": { node: NODE, health, last_reconcile_report: null },
      "GET /admin/node/sessions": [SESSION],
      "POST /admin/node/actions": () => undefined,
      "POST /admin/node/probe": HEALTH,
      "POST /admin/node/reconcile": {
        node_id: 1,
        started_at: "2026-10-23T10:00:00Z",
        finished_at: "2026-10-23T10:00:01Z",
        drifts: [{ kind: "missing_in_allowed_list", details: { username: "c5-d1" } }],
        error: null,
      },
    },
  });
}

const actions = (calls: { method: string; url: URL; body: unknown }[]) =>
  calls.filter((c) => c.url.pathname === "/admin/node/actions");

test("stop_requires_confirmation", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await user.click(await screen.findByRole("button", { name: "Остановить" }));
  expect(actions(calls)).toHaveLength(0);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Остановить" }));
  await waitFor(() => expect(actions(calls)).toHaveLength(1));
  expect(actions(calls)[0].body).toEqual({ action: "stop" });
});

test("restart_and_reload_and_start_send_their_action", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await user.click(await screen.findByRole("button", { name: "Запустить" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Запустить" }));
  await waitFor(() => expect(actions(calls)).toHaveLength(1));
  expect(actions(calls)[0].body).toEqual({ action: "start" });
});

test("disconnect_user_sends_username", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await user.click(await screen.findByRole("button", { name: "Отключить" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Отключить" }));
  await waitFor(() => expect(actions(calls)).toHaveLength(1));
  expect(actions(calls)[0].body).toEqual({ action: "disconnect_user", username: "c5-d1" });
});

test("reconcile_shows_drifts", async () => {
  const user = userEvent.setup();
  page();
  await user.click(await screen.findByRole("button", { name: "Сверить" }));
  expect(await screen.findByText("missing_in_allowed_list")).toBeInTheDocument();
});

test("null_health_shows_no_data", async () => {
  page(null);
  expect((await screen.findAllByText("нет данных")).length).toBeGreaterThan(0);
  expect(screen.queryByText("не отвечает")).toBeNull();
});

test("logs_start_and_stop_close_the_stream", async () => {
  const user = userEvent.setup();
  page();
  await user.click(await screen.findByRole("button", { name: "Показать логи" }));
  const source = FakeEventSource.instances[0];
  expect(source.url).toBe("/admin/node/logs?tail=200");
  act(() => source.emit("message", "ocserv started"));
  expect(await screen.findByText("ocserv started")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Остановить логи" }));
  expect(source.closed).toBe(true);
});

test("log_stream_error_event_is_shown_as_unavailable", async () => {
  const user = userEvent.setup();
  page();
  await user.click(await screen.findByRole("button", { name: "Показать логи" }));
  act(() => FakeEventSource.instances[0].emit("error", "node unavailable"));
  expect(await screen.findByText("Нода недоступна")).toBeInTheDocument();
});

test("leaving_the_page_closes_the_stream", async () => {
  const user = userEvent.setup();
  const { unmount } = page();
  await user.click(await screen.findByRole("button", { name: "Показать логи" }));
  unmount();
  expect(FakeEventSource.instances[0].closed).toBe(true);
});
