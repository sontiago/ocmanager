import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiError, renderRoutes } from "../test/utils";
import { PromoPage } from "./Promo";

const CODE = {
  id: 1,
  code: "spring14",
  kind: "days",
  value: 14,
  max_uses: 10,
  uses: 3,
  expires_at: null,
  is_active: true,
  created_at: "2026-10-01T00:00:00Z",
};

function page(extra: Record<string, never | object | (() => object)> = {}, codes: object[] = [CODE]) {
  return renderRoutes([{ path: "/promo", element: <PromoPage /> }], {
    route: "/promo",
    handlers: {
      "GET /admin/promo-codes": codes,
      "GET /admin/promo-codes/1/redemptions": [
        { id: 7, client_id: 5, client_name: "Anna", kind: "days", value: 14, redeemed_at: "2026-10-02T00:00:00Z" },
      ],
      ...extra,
    } as never,
  });
}

const sent = (calls: { method: string; url: URL; body: unknown }[], method: string) =>
  calls.filter((c) => c.method === method);

test("lists_codes_with_usage", async () => {
  page();
  const row = (await screen.findByText("spring14")).closest("tr")!;
  expect(within(row).getByText("3 / 10")).toBeInTheDocument();
  expect(within(row).getByText("+14 дн.")).toBeInTheDocument();
});

test("traffic_codes_are_shown_in_gb_and_unlimited_uses_as_infinity", async () => {
  page({}, [{ ...CODE, kind: "traffic", value: 50, max_uses: null, uses: 2 }]);
  const row = (await screen.findByText("spring14")).closest("tr")!;
  expect(within(row).getByText("+50 ГБ")).toBeInTheDocument();
  expect(within(row).getByText("2 / ∞")).toBeInTheDocument();
});

test("create_sends_the_code_kind_and_value", async () => {
  const user = userEvent.setup();
  const { calls } = page({ "POST /admin/promo-codes": { ...CODE, id: 2, code: "gb50" } });
  await user.click(await screen.findByRole("button", { name: "Новый промокод" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Код"), "gb50");
  await user.selectOptions(within(dialog).getByLabelText("Награда"), "traffic");
  await user.type(within(dialog).getByLabelText("Значение"), "50");
  await user.type(within(dialog).getByLabelText("Лимит использований"), "100");
  await user.click(within(dialog).getByRole("button", { name: "Создать" }));
  await waitFor(() => expect(sent(calls, "POST")).toHaveLength(1));
  expect(sent(calls, "POST")[0].body).toEqual({ code: "gb50", kind: "traffic", value: 50, max_uses: 100 });
});

test("create_omits_empty_limits", async () => {
  const user = userEvent.setup();
  const { calls } = page({ "POST /admin/promo-codes": { ...CODE, id: 2 } });
  await user.click(await screen.findByRole("button", { name: "Новый промокод" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Код"), "bonus7");
  await user.type(within(dialog).getByLabelText("Значение"), "7");
  await user.click(within(dialog).getByRole("button", { name: "Создать" }));
  await waitFor(() => expect(sent(calls, "POST")).toHaveLength(1));
  expect(sent(calls, "POST")[0].body).toEqual({ code: "bonus7", kind: "days", value: 7 });
});

test("create_shows_the_servers_error", async () => {
  const user = userEvent.setup();
  page({ "POST /admin/promo-codes": apiError(409, "conflict", "promo code already exists") });
  await user.click(await screen.findByRole("button", { name: "Новый промокод" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Код"), "spring14");
  await user.type(within(dialog).getByLabelText("Значение"), "7");
  await user.click(within(dialog).getByRole("button", { name: "Создать" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("promo code already exists");
});

test("switching_a_code_off_patches_is_active", async () => {
  const user = userEvent.setup();
  const { calls } = page({ "PATCH /admin/promo-codes/1": { ...CODE, is_active: false } });
  await user.click(await screen.findByRole("button", { name: "Выключить spring14" }));
  await waitFor(() => expect(sent(calls, "PATCH")).toHaveLength(1));
  expect(sent(calls, "PATCH")[0].body).toEqual({ is_active: false });
});

test("an_inactive_code_can_be_switched_back_on", async () => {
  const user = userEvent.setup();
  const { calls } = page({ "PATCH /admin/promo-codes/1": CODE }, [{ ...CODE, is_active: false }]);
  await user.click(await screen.findByRole("button", { name: "Включить spring14" }));
  await waitFor(() => expect(sent(calls, "PATCH")).toHaveLength(1));
  expect(sent(calls, "PATCH")[0].body).toEqual({ is_active: true });
});

test("redemptions_expand_and_link_to_the_client", async () => {
  const user = userEvent.setup();
  page();
  await user.click(await screen.findByRole("button", { name: "Погашения spring14" }));
  const link = await screen.findByRole("link", { name: "Anna" });
  expect(link).toHaveAttribute("href", "/clients/5");
});
