import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiError, renderRoutes } from "../test/utils";
import { PlansPage } from "./Plans";

const PLAN = {
  id: 1,
  code: "pro",
  name_i18n: { ru: "Про", en: "Pro" },
  description_i18n: null,
  duration_days: 30,
  device_limit: 3,
  traffic_limit_bytes: null,
  speed_limit_kbps: null,
  price_amount: 29900,
  currency: "RUB",
  provider_product_ids: {},
  is_active: true,
  is_trial: false,
  sort_order: 0,
};

function page(extra: Record<string, object | Response | (() => object | Response)> = {}) {
  return renderRoutes([{ path: "/plans", element: <PlansPage /> }], {
    route: "/plans",
    handlers: { "GET /admin/plans": [PLAN], ...extra },
  });
}

const body = (calls: { method: string; url: URL; body: unknown }[], method: string) =>
  calls.find((c) => c.method === method)?.body;

test("patch_sends_only_changed_fields", async () => {
  const user = userEvent.setup();
  const { calls } = page({ "PATCH /admin/plans/pro": PLAN });
  await user.click(await screen.findByRole("button", { name: "Изменить Про" }));
  const dialog = await screen.findByRole("dialog");
  const devices = within(dialog).getByLabelText("Лимит устройств");
  await user.clear(devices);
  await user.type(devices, "5");
  await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(body(calls, "PATCH")).toBeDefined());
  expect(body(calls, "PATCH")).toEqual({ device_limit: 5 });
});

test("code_field_disabled_when_editing", async () => {
  const user = userEvent.setup();
  page();
  await user.click(await screen.findByRole("button", { name: "Изменить Про" }));
  expect(within(await screen.findByRole("dialog")).getByLabelText("Код")).toBeDisabled();
});

test("price_entered_in_major_units_sent_in_minor", async () => {
  const user = userEvent.setup();
  const { calls } = page({ "POST /admin/plans": { ...PLAN, code: "new" } });
  await user.click(await screen.findByRole("button", { name: "Новый тариф" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Код"), "new");
  await user.type(within(dialog).getByLabelText("Название (ru)"), "Новый");
  await user.type(within(dialog).getByLabelText("Название (en)"), "New");
  await user.type(within(dialog).getByLabelText("Цена"), "299.50");
  await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(body(calls, "POST")).toBeDefined());
  expect(body(calls, "POST")).toMatchObject({
    code: "new",
    price_amount: 29950,
    currency: "RUB",
    name_i18n: { ru: "Новый", en: "New" },
  });
});

test("shows_validation_error_from_422", async () => {
  const user = userEvent.setup();
  page({ "PATCH /admin/plans/pro": apiError(422, "validation_error", "price_amount: too large") });
  await user.click(await screen.findByRole("button", { name: "Изменить Про" }));
  const dialog = await screen.findByRole("dialog");
  const price = within(dialog).getByLabelText("Цена");
  await user.clear(price);
  await user.type(price, "5");
  await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("price_amount: too large");
});

test("unchanged_form_does_not_call_api", async () => {
  const user = userEvent.setup();
  const { calls } = page();
  await user.click(await screen.findByRole("button", { name: "Изменить Про" }));
  await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Сохранить" }));
  expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
});
