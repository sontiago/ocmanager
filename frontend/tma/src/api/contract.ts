import type {
  Checkout,
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
} from "./types";

/**
 * Всё, что TMA просит у бэкенда. Две реализации: mock/client.ts и http.ts.
 * Любой метод при неуспехе бросает ApiError — других способов сообщить об
 * ошибке у реализаций нет.
 */
export interface ApiClient {
  /** GET /tma/me */
  getMe(): Promise<Me>;
  /** GET /tma/plans — только активные, отсортированы по sort_order */
  listPlans(): Promise<Plan[]>;
  /** GET /tma/subscription — null, если подписки никогда не было */
  getSubscription(): Promise<Subscription | null>;
  /** POST /tma/subscription/trial */
  startTrial(): Promise<Subscription>;
  /** POST /tma/checkout */
  createCheckout(planCode: string): Promise<Checkout>;
  /** GET /tma/devices — только неотозванные */
  listDevices(): Promise<Device[]>;
  /** POST /tma/devices — пароль и ссылка приходят один раз */
  createDevice(input: CreateDeviceInput): Promise<IssuedDevice>;
  /** DELETE /tma/devices/{id} */
  revokeDevice(deviceId: string): Promise<void>;
  /** GET /tma/connection */
  getConnection(): Promise<ConnectionInfo>;
}
