import type { components } from "./generated";
import type {
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
} from "./types";

type Schemas = components["schemas"];

/** Компилируется, только если типы взаимно присваиваемы; иначе — `never` и ошибка `tsc`. */
type AssertSame<T, U> = [T] extends [U] ? ([U] extends [T] ? true : never) : never;

// Каждая строка ломает проверку, если бэкенд изменил форму ответа или фронтенд — свой тип.
export const meMatches: AssertSame<Me, Schemas["MeOut"]> = true;
export const planMatches: AssertSame<Plan, Schemas["PlanOut"]> = true;
export const subscriptionMatches: AssertSame<Subscription, Schemas["SubscriptionOut"]> = true;
export const deviceMatches: AssertSame<Device, Schemas["DeviceOut"]> = true;
export const issuedMatches: AssertSame<IssuedDevice, Schemas["IssuedDeviceOut"]> = true;
export const connectionMatches: AssertSame<ConnectionInfo, Schemas["ConnectionOut"]> = true;
export const createInputMatches: AssertSame<CreateDeviceInput, Schemas["CreateDeviceIn"]> = true;
