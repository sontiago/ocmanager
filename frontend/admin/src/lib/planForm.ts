import type { S } from "../api/types";

type Plan = S<"PlanOut">;
type Create = S<"PlanCreate">;
type Update = S<"PlanUpdate">;

const GB = 1024 ** 3;

/** Поля формы тарифа — строки, как их вводит человек; деньги в основных единицах, трафик в ГБ. */
export interface PlanForm {
  code: string;
  nameRu: string;
  nameEn: string;
  descRu: string;
  descEn: string;
  durationDays: string;
  deviceLimit: string;
  trafficGb: string;
  speedKbps: string;
  price: string;
  currency: string;
  products: string;
  isActive: boolean;
  sortOrder: string;
}

export const EMPTY_FORM: PlanForm = {
  code: "",
  nameRu: "",
  nameEn: "",
  descRu: "",
  descEn: "",
  durationDays: "30",
  deviceLimit: "1",
  trafficGb: "",
  speedKbps: "",
  price: "",
  currency: "RUB",
  products: "{}",
  isActive: true,
  sortOrder: "0",
};

export function toForm(p: Plan): PlanForm {
  return {
    code: p.code,
    nameRu: p.name_i18n.ru ?? "",
    nameEn: p.name_i18n.en ?? "",
    descRu: p.description_i18n?.ru ?? "",
    descEn: p.description_i18n?.en ?? "",
    durationDays: String(p.duration_days),
    deviceLimit: String(p.device_limit),
    trafficGb: p.traffic_limit_bytes === null ? "" : String(p.traffic_limit_bytes / GB),
    speedKbps: p.speed_limit_kbps === null ? "" : String(p.speed_limit_kbps),
    price: String(p.price_amount / 100),
    currency: p.currency,
    products: JSON.stringify(p.provider_product_ids ?? {}),
    isActive: p.is_active,
    sortOrder: String(p.sort_order),
  };
}

const names = (ru: string, en: string) => ({
  ...(ru ? { ru } : {}),
  ...(en ? { en } : {}),
});

function values(f: PlanForm) {
  const description = names(f.descRu, f.descEn);
  return {
    name_i18n: names(f.nameRu, f.nameEn),
    description_i18n: Object.keys(description).length ? description : null,
    duration_days: Number(f.durationDays),
    device_limit: Number(f.deviceLimit),
    traffic_limit_bytes: f.trafficGb === "" ? null : Math.round(Number(f.trafficGb) * GB),
    speed_limit_kbps: f.speedKbps === "" ? null : Number(f.speedKbps),
    price_amount: Math.round(Number(f.price) * 100),
    currency: f.currency.trim().toUpperCase(),
    provider_product_ids: JSON.parse(f.products || "{}") as Record<string, unknown>,
    is_active: f.isActive,
    sort_order: Number(f.sortOrder),
  };
}

/** Невалидный JSON в «Продуктах провайдеров» → null: форма покажет ошибку у поля. */
export function productsValid(f: PlanForm): boolean {
  try {
    const v: unknown = JSON.parse(f.products || "{}");
    return typeof v === "object" && v !== null && !Array.isArray(v);
  } catch {
    return false;
  }
}

export function toCreate(f: PlanForm): Create {
  return { code: f.code, ...values(f) } as Create;
}

/** Только изменившиеся поля: PATCH не должен затирать то, чего человек не трогал. */
export function toPatch(original: Plan, f: PlanForm): Update {
  const before = values(toForm(original));
  const after = values(f);
  const patch: Record<string, unknown> = {};
  for (const key of Object.keys(after) as (keyof typeof after)[]) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) patch[key] = after[key];
  }
  return patch as Update;
}
