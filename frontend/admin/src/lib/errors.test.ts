import ru from "../i18n/ru.json";
import { ApiError } from "../api/errors";
import { errorText } from "./errors";

const dict = ru as Record<string, string>;
const t = (key: string) => dict[key] ?? key;

test("a_known_code_is_shown_in_the_interface_language_not_the_servers_english", () => {
  const err = new ApiError("not_found", 404, "client not found");
  expect(errorText(err, t)).toBe(dict["apiError.not_found"]);
  expect(errorText(err, t)).not.toContain("client not found");
});

test("every_code_the_admin_api_can_send_has_a_translation", () => {
  const codes = [
    "unauthorized",
    "forbidden",
    "not_found",
    "conflict",
    "validation_error",
    "invalid_transition",
    "subscription_inactive",
    "device_limit_reached",
    "trial_already_used",
    "rate_limited",
    "node_unavailable",
    "csrf_failed",
    "totp_required",
    "promo_invalid",
    "promo_already_used",
    "not_applicable",
    "pki_not_ready",
    "network",
    "internal",
  ];
  for (const code of codes) expect(dict[`apiError.${code}`], code).toBeTruthy();
});

test("validation_and_conflict_keep_the_servers_detail_because_it_names_the_field", () => {
  const v = errorText(new ApiError("validation_error", 422, "price_amount: too large"), t);
  expect(v).toContain(dict["apiError.validation_error"]);
  expect(v).toContain("price_amount: too large");
  const c = errorText(new ApiError("conflict", 409, "promo code already exists"), t);
  expect(c).toContain("promo code already exists");
});

test("a_detail_equal_to_the_code_is_not_repeated", () => {
  expect(errorText(new ApiError("conflict", 409, "conflict"), t)).toBe(dict["apiError.conflict"]);
});

test("an_unknown_code_or_a_foreign_error_falls_back_to_the_generic_text", () => {
  expect(errorText(new ApiError("brand_new", 400, "x"), t)).toBe(dict["common.error"]);
  expect(errorText(new Error("boom"), t)).toBe(dict["common.error"]);
  expect(errorText(undefined, t)).toBe(dict["common.error"]);
});

test("a_bare_http_status_code_is_translated_by_its_family", () => {
  expect(errorText(new ApiError("http_502", 502), t)).toBe(dict["apiError.internal"]);
});
