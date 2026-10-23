import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiError, renderRoutes } from "../test/utils";
import { DevicesPage } from "./Devices";

const dev = (over: Record<string, unknown> = {}) => ({
  id: 11,
  client_id: 5,
  telegram_id: 777,
  client_name: "Bob",
  seq: 1,
  name: "iPhone",
  platform: "ios",
  username: "c5-d1",
  issued_at: "2026-10-01T00:00:00Z",
  cert_expires_at: "2027-10-01T00:00:00Z",
  revoked_at: null,
  revocation_reason: null,
  last_seen_at: null,
  is_online: true,
  ...over,
});

function page(devices: unknown[], route = "/devices") {
  return renderRoutes([{ path: "/devices", element: <DevicesPage /> }], {
    route,
    handlers: {
      "GET /admin/devices": { items: devices, total: devices.length, limit: 50, offset: 0 },
      "GET /admin/devices/11/sessions": {
        items: [
          {
            id: 1,
            username: "c5-d1",
            started_at: "2026-10-22T10:00:00Z",
            ended_at: null,
            duration_sec: 3900,
            client_ip: "1.2.3.4",
            vpn_ip: "10.0.0.2",
            bytes_in: 1024,
            bytes_out: 2048,
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
      },
      "POST /admin/devices/11/revoke": dev({ revoked_at: "2026-10-23T00:00:00Z" }),
    },
  });
}

test("revoke_requires_nonempty_reason", async () => {
  const user = userEvent.setup();
  page([dev()]);
  await user.click(await screen.findByRole("button", { name: "Отозвать" }));
  const dialog = screen.getByRole("dialog");
  const confirm = within(dialog).getByRole("button", { name: "Отозвать" });
  expect(confirm).toBeDisabled();
  await user.type(within(dialog).getByLabelText("Причина"), "   ");
  expect(confirm).toBeDisabled();
});

test("revoke_sends_reason", async () => {
  const user = userEvent.setup();
  const { calls } = page([dev()]);
  await user.click(await screen.findByRole("button", { name: "Отозвать" }));
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText("Причина"), "потерян телефон");
  await user.click(within(dialog).getByRole("button", { name: "Отозвать" }));
  await waitFor(() => expect(calls.some((c) => c.url.pathname === "/admin/devices/11/revoke")).toBe(true));
  expect(calls.find((c) => c.url.pathname === "/admin/devices/11/revoke")?.body).toEqual({
    reason: "потерян телефон",
  });
});

test("online_null_shows_no_data", async () => {
  page([dev({ is_online: null })]);
  expect(await screen.findByText("нет данных")).toBeInTheDocument();
});

test("revoked_device_has_no_revoke_button", async () => {
  page([dev({ revoked_at: "2026-10-20T00:00:00Z", revocation_reason: "lost" })]);
  await screen.findByText("iPhone");
  expect(screen.queryByRole("button", { name: "Отозвать" })).toBeNull();
  expect(screen.getByText("отозвано")).toBeInTheDocument();
});

test("online_filter_sent", async () => {
  const user = userEvent.setup();
  const { calls } = page([dev()]);
  await screen.findByText("iPhone");
  await user.selectOptions(screen.getByLabelText("Онлайн"), "true");
  await waitFor(() =>
    expect(calls.filter((c) => c.url.pathname === "/admin/devices").at(-1)!.url.searchParams.get("online")).toBe("true"),
  );
});

test("sessions_expand_shows_history", async () => {
  const user = userEvent.setup();
  page([dev()]);
  await user.click(await screen.findByRole("button", { name: "Сессии" }));
  expect(await screen.findByText("1.2.3.4")).toBeInTheDocument();
});

test("search_box_follows_the_url_on_back_navigation", async () => {
  const { router } = page([dev()], "/devices?q=c5");
  const box = await screen.findByLabelText("Поиск");
  expect(box).toHaveValue("c5");
  await act(async () => {
    await router.navigate("/devices");
  });
  expect(box).toHaveValue("");
});

test("online_filter_without_node_data_explains_itself_instead_of_a_generic_error", async () => {
  renderRoutes([{ path: "/devices", element: <DevicesPage /> }], {
    route: "/devices?online=true",
    handlers: { "GET /admin/devices": apiError(503, "node_unavailable") },
  });
  expect(await screen.findByText(/нет данных о состоянии ноды/i)).toBeInTheDocument();
  expect(screen.queryByText("Не удалось загрузить")).toBeNull();
});

test("a_503_without_the_online_filter_stays_a_normal_error", async () => {
  renderRoutes([{ path: "/devices", element: <DevicesPage /> }], {
    route: "/devices",
    handlers: { "GET /admin/devices": apiError(503, "node_unavailable") },
  });
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText(/нет данных о состоянии ноды/i)).toBeNull();
});
