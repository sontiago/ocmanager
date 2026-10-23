import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiError, renderRoutes } from "../test/utils";
import { SettingsPage } from "./Settings";

const SETTINGS = {
  runtime: {
    trial_days: 3,
    trial_traffic_bytes: 5 * 1024 ** 3,
    default_lang: "ru",
    support_url: null,
    admin_chat_ids: [11, 22],
    expiry_reminder_days: [3, 1],
    traffic_retention_days: 90,
  },
  environment: { env: "production", vpn_host: "vpn.example.com", ocserv_container: "ocm-ocserv", version: "1.2.3" },
};

function page(patch: object | Response = SETTINGS) {
  return renderRoutes([{ path: "/settings", element: <SettingsPage /> }], {
    route: "/settings",
    handlers: { "GET /admin/settings": SETTINGS, "PATCH /admin/settings": patch },
  });
}

const patches = (calls: { method: string; body: unknown }[]) => calls.filter((c) => c.method === "PATCH");

test("patch_contains_only_changed_keys", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  const days = await screen.findByLabelText("Дней пробного периода");
  await user.clear(days);
  await user.type(days, "7");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(patches(calls)).toHaveLength(1));
  expect(patches(calls)[0].body).toEqual({ trial_days: 7 });
});

test("lists_are_parsed_from_comma_separated_text", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  const ids = await screen.findByLabelText("Chat ID админов (через запятую)");
  await user.clear(ids);
  await user.type(ids, "11, 33");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(patches(calls)).toHaveLength(1));
  expect(patches(calls)[0].body).toEqual({ admin_chat_ids: [11, 33] });
});

test("unchanged_form_does_not_call_api", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await screen.findByLabelText("Дней пробного периода");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(patches(calls)).toHaveLength(0);
});

test("environment_is_readonly", async () => {
  page();
  expect(await screen.findByText("vpn.example.com")).toBeInTheDocument();
  expect(screen.getByText("1.2.3")).toBeInTheDocument();
  expect(screen.queryByDisplayValue("vpn.example.com")).toBeNull();
});

test("shows_422_error", async () => {
  const user = userEvent.setup();
  page(apiError(422, "validation_error", "trial_days: must be <= 30"));
  const days = await screen.findByLabelText("Дней пробного периода");
  await user.clear(days);
  await user.type(days, "99");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("trial_days: must be <= 30");
});

test("a_refetch_with_newer_server_values_is_not_overwritten_by_the_old_form", async () => {
  const user = userEvent.setup();
  let serverRetention = 90;
  const { calls, queryClient } = renderRoutes([{ path: "/settings", element: <SettingsPage /> }], {
    route: "/settings",
    handlers: {
      "GET /admin/settings": () => ({
        ...SETTINGS,
        runtime: { ...SETTINGS.runtime, traffic_retention_days: serverRetention },
      }),
      "PATCH /admin/settings": SETTINGS,
    },
  });
  const days = await screen.findByLabelText("Дней пробного периода");
  serverRetention = 120; // кто-то поменял другое поле, пока форма открыта
  await queryClient.invalidateQueries({ queryKey: ["settings"] });
  await user.clear(days);
  await user.type(days, "7");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(patches(calls)).toHaveLength(1));
  expect(patches(calls)[0].body).toEqual({ trial_days: 7 }); // retention не затёрт старым значением
});

test("an_empty_number_field_is_refused_instead_of_sending_zero", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  const days = await screen.findByLabelText("Дней пробного периода");
  await user.clear(days);
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Заполните числа");
  expect(patches(calls)).toHaveLength(0);
});

test("a_non_numeric_list_entry_is_refused", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  const ids = await screen.findByLabelText("Chat ID админов (через запятую)");
  await user.clear(ids);
  await user.type(ids, "11, abc");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Заполните числа");
  expect(patches(calls)).toHaveLength(0);
});

test("an_empty_support_link_is_a_valid_clear", async () => {
  const user = userEvent.setup();
  const { calls } = renderRoutes([{ path: "/settings", element: <SettingsPage /> }], {
    route: "/settings",
    handlers: {
      "GET /admin/settings": {
        ...SETTINGS,
        runtime: { ...SETTINGS.runtime, support_url: "https://t.me/help" },
      },
      "PATCH /admin/settings": SETTINGS,
    },
  });
  const link = await screen.findByLabelText("Ссылка на поддержку");
  await user.clear(link);
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(patches(calls)).toHaveLength(1));
  expect(patches(calls)[0].body).toEqual({ support_url: null });
});
