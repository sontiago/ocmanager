import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link } from "react-router";
import { apiError, renderRoutes } from "../test/utils";
import { useApiClient } from "../api/session";
import { LoginPage } from "../pages/Login";
import { RequireAuth } from "./RequireAuth";

function Secret() {
  const client = useApiClient();
  return (
    <div>
      <p>secret</p>
      <Link to="/other">other</Link>
      <button onClick={() => void client.get("/overview").catch(() => undefined)}>poll</button>
    </div>
  );
}

const routes = [
  { path: "/login", element: <LoginPage /> },
  { element: <RequireAuth />, children: [{ path: "/secret", element: <Secret /> }, { path: "/other", element: <p>other page</p> }] },
];

test("authed_user_sees_protected_page", async () => {
  renderRoutes(routes, { route: "/secret" });
  expect(await screen.findByText("secret")).toBeInTheDocument();
});

test("anon_redirects_to_login_with_from", async () => {
  const { router } = renderRoutes(routes, {
    route: "/secret",
    handlers: { "GET /admin/auth/me": apiError(401, "unauthorized") },
  });
  expect(await screen.findByLabelText("Логин")).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/login");
  expect((router.state.location.state as { from: string }).from).toBe("/secret");
});

test("session_expiry_midwork_redirects", async () => {
  const user = userEvent.setup();
  const { router } = renderRoutes(routes, {
    route: "/secret",
    handlers: { "GET /admin/overview": apiError(401, "unauthorized") },
  });
  await user.click(await screen.findByRole("button", { name: "poll" }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  expect((router.state.location.state as { from: string }).from).toBe("/secret");
});
