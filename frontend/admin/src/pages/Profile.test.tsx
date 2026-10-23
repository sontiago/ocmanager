import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ADMIN, renderRoutes } from "../test/utils";
import { ProfilePage } from "./Profile";

const SESSIONS = [
  { id: 1, created_at: "2026-10-23T08:00:00Z", last_seen_at: "2026-10-23T09:00:00Z", expires_at: "2026-10-30T08:00:00Z", ip: "127.0.0.1", user_agent: "Chrome", current: true },
  { id: 2, created_at: "2026-10-20T08:00:00Z", last_seen_at: "2026-10-21T09:00:00Z", expires_at: "2026-10-27T08:00:00Z", ip: "10.0.0.9", user_agent: "Firefox", current: false },
];

function page(extra: Record<string, object | (() => object | undefined)> = {}) {
  return renderRoutes([{ path: "/profile", element: <ProfilePage /> }], {
    route: "/profile",
    handlers: { "GET /admin/auth/sessions": SESSIONS, ...extra },
  });
}

test("password_change_sends_both_fields", async () => {
  const user = userEvent.setup();
  const { calls } = page({ "POST /admin/auth/password": () => undefined });
  await user.type(await screen.findByLabelText("Текущий пароль"), "old-pass");
  await user.type(screen.getByLabelText("Новый пароль"), "new-pass-123");
  await user.click(screen.getByRole("button", { name: "Сменить пароль" }));
  await waitFor(() => expect(calls.some((c) => c.url.pathname === "/admin/auth/password")).toBe(true));
  expect(calls.find((c) => c.url.pathname === "/admin/auth/password")?.body).toEqual({
    current_password: "old-pass",
    new_password: "new-pass-123",
  });
});

test("totp_setup_then_confirm_flow", async () => {
  const user = userEvent.setup();
  let enabled = false;
  const { calls } = page({
    "GET /admin/auth/me": () => ({ admin: { ...ADMIN, totp_enabled: enabled }, csrf_token: "c" }),
    "POST /admin/auth/totp/setup": { otpauth_uri: "otpauth://totp/x?secret=ABCDEF", secret: "ABCDEF" },
    "POST /admin/auth/totp/confirm": () => {
      enabled = true;
      return undefined;
    },
  });
  await user.click(await screen.findByRole("button", { name: "Включить 2FA" }));
  expect(await screen.findByText("ABCDEF")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Код из приложения"), "123456");
  await user.click(screen.getByRole("button", { name: "Подтвердить код" }));
  await waitFor(() => expect(calls.some((c) => c.url.pathname === "/admin/auth/totp/confirm")).toBe(true));
  expect(calls.find((c) => c.url.pathname === "/admin/auth/totp/confirm")?.body).toEqual({ code: "123456" });
  expect(await screen.findByRole("button", { name: "Отключить 2FA" })).toBeInTheDocument();
});

test("closing_session_asks_confirmation", async () => {
  const user = userEvent.setup();
  const { calls } = page({ "DELETE /admin/auth/sessions/2": () => undefined });
  await user.click(await screen.findByRole("button", { name: "Закрыть сессию" }));
  expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Закрыть сессию" }));
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
});

test("current_session_has_no_close_button", async () => {
  page();
  await screen.findByText("Firefox");
  expect(screen.getAllByRole("button", { name: "Закрыть сессию" })).toHaveLength(1);
  expect(screen.getByText("текущая")).toBeInTheDocument();
});

test("the_totp_confirm_button_is_locked_while_the_request_is_in_flight", async () => {
  const user = userEvent.setup();
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  page({
    "POST /admin/auth/totp/setup": { otpauth_uri: "otpauth://totp/x?secret=ABCDEF", secret: "ABCDEF" },
    "POST /admin/auth/totp/confirm": () => gate.then(() => undefined),
  });
  await user.click(await screen.findByRole("button", { name: "Включить 2FA" }));
  await user.type(await screen.findByLabelText("Код из приложения"), "123456");
  const confirm = screen.getByRole("button", { name: "Подтвердить код" });
  await user.click(confirm);
  await waitFor(() => expect(confirm).toBeDisabled());
  release();
});
