import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoutes } from "../test/utils";
import { AuditPage } from "./Audit";

const ROW = {
  id: 1,
  created_at: "2026-10-23T09:00:00Z",
  actor_type: "admin",
  actor_id: "1",
  ip: "127.0.0.1",
  action: "client.block",
  target_type: "client",
  target_id: "5",
  details: { reason: "abuse" },
};

function page(route = "/audit") {
  return renderRoutes([{ path: "/audit", element: <AuditPage /> }], {
    route,
    handlers: { "GET /admin/audit": { items: [ROW], total: 1, limit: 50, offset: 0 } },
  });
}

const last = (calls: { url: URL }[]) =>
  calls.filter((c) => c.url.pathname === "/admin/audit").at(-1)!.url.searchParams;

test("filters_go_to_query_and_reset_offset", async () => {
  const user = userEvent.setup();
  const { calls } = page("/audit?offset=50");
  await screen.findByText("client.block");
  expect(last(calls).get("offset")).toBe("50");
  await user.selectOptions(screen.getByLabelText("Кто"), "system");
  await waitFor(() => expect(last(calls).get("actor_type")).toBe("system"));
  expect(last(calls).get("offset")).toBe("0");
});

test("details_expand", async () => {
  const user = userEvent.setup();
  page();
  await user.click(await screen.findByRole("button", { name: "Детали" }));
  expect(await screen.findByText(/"reason": "abuse"/)).toBeInTheDocument();
});

test("date_filters_sent_as_utc_iso", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await screen.findByText("client.block");
  await user.type(screen.getByLabelText("С даты"), "2026-10-01");
  await waitFor(() => expect(last(calls).get("since")).toBe("2026-10-01T00:00:00.000Z"));
});
