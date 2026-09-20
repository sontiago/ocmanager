import type { Subscription, SubscriptionStatus } from "../api/types";
import type { MessageKey } from "../i18n/ru";

const DAY = 86_400_000;

/**
 * cancelled входит сюда сознательно: отмена автопродления не отключает
 * доступ, клиент дорабатывает оплаченный период до expires_at.
 */
const LIVE: ReadonlySet<SubscriptionStatus> = new Set<SubscriptionStatus>([
  "trial",
  "active",
  "cancelled",
]);

export function isLive(sub: Subscription | null): boolean {
  return sub !== null && LIVE.has(sub.status);
}

export function daysLeft(sub: Subscription, now: number = Date.now()): number {
  if (sub.expires_at === null) return Infinity;
  const ms = Date.parse(sub.expires_at) - now;
  if (Number.isNaN(ms)) return 0;
  return Math.max(0, Math.ceil(ms / DAY));
}

/** null = безлимитный тариф. Число всегда в диапазоне 0…100. */
export function trafficPercent(sub: Subscription): number | null {
  if (sub.traffic_limit_bytes === null || sub.traffic_limit_bytes <= 0) {
    return null;
  }
  const ratio = (sub.traffic_used_bytes / sub.traffic_limit_bytes) * 100;
  return Math.min(100, Math.max(0, Math.round(ratio)));
}

export function canIssueDevice(sub: Subscription | null): boolean {
  return isLive(sub) && sub!.devices_used < sub!.device_limit;
}

/** Ключ без приведения: недостающий status.* станет ошибкой компиляции. */
export function statusMessageKey(sub: Subscription): MessageKey {
  return `status.${sub.status}`;
}
