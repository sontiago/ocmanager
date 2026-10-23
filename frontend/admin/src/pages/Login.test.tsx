import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiError, ADMIN, renderRoutes } from "../test/utils";
import { LoginPage } from "./Login";

const routes = [
  { path: "/login", element: <LoginPage /> },
  { path: "/clients", element: <p>clients page</p> },
  { path: "/", element: <p>home page</p> },
];
const anon = { "GET /admin/auth/me": apiError(401, "unauthorized") };

async function fill(user: ReturnType<typeof userEvent.setup>, password = "pw") {
  await user.type(await screen.findByLabelText("Логин"), "root");
  await user.type(screen.getByLabelText("Пароль"), password);
}

test("submits_username_password", async () => {
  const user = userEvent.setup();
  const { calls } = renderRoutes(routes, {
    route: "/login",
    handlers: { ...anon, "POST /admin/auth/login": { admin: ADMIN, csrf_token: "c" } },
  });
  await fill(user);
  await user.click(screen.getByRole("button", { name: "Войти" }));
  await waitFor(() => expect(calls.some((c) => c.url.pathname === "/admin/auth/login")).toBe(true));
  expect(calls.find((c) => c.url.pathname === "/admin/auth/login")?.body).toEqual({
    username: "root",
    password: "pw",
  });
});

test("shows_totp_field_after_totp_required_error", async () => {
  const user = userEvent.setup();
  let attempt = 0;
  const { calls } = renderRoutes(routes, {
    route: "/login",
    handlers: {
      ...anon,
      "POST /admin/auth/login": () =>
        ++attempt === 1 ? apiError(401, "totp_required") : { admin: ADMIN, csrf_token: "c" },
    },
  });
  await fill(user);
  expect(screen.queryByLabelText("Код из приложения")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Войти" }));
  await user.type(await screen.findByLabelText("Код из приложения"), "123456");
  await user.click(screen.getByRole("button", { name: "Войти" }));
  await waitFor(() => expect(attempt).toBe(2));
  const login = calls.filter((c) => c.url.pathname === "/admin/auth/login");
  expect(login[1].body).toEqual({ username: "root", password: "pw", totp_code: "123456" });
});

test("shows_error_message_on_bad_credentials", async () => {
  const user = userEvent.setup();
  renderRoutes(routes, {
    route: "/login",
    handlers: { ...anon, "POST /admin/auth/login": apiError(401, "unauthorized") },
  });
  await fill(user);
  await user.click(screen.getByRole("button", { name: "Войти" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Неверный логин, пароль или код");
});

test("redirects_to_from_after_login", async () => {
  const user = userEvent.setup();
  renderRoutes(routes, {
    route: { pathname: "/login", state: { from: "/clients" } },
    handlers: { ...anon, "POST /admin/auth/login": { admin: ADMIN, csrf_token: "c" } },
  });
  await fill(user);
  await user.click(screen.getByRole("button", { name: "Войти" }));
  expect(await screen.findByText("clients page")).toBeInTheDocument();
});

test("already_authed_user_is_sent_home", async () => {
  renderRoutes(routes, { route: "/login" });
  expect(await screen.findByText("home page")).toBeInTheDocument();
});
