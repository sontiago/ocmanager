import type { Platform } from "../api/types";

/** Названия ОС — имена собственные: одинаковы в обеих локалях, в i18n не идут. */
export const PLATFORM_LABEL: Record<Platform, string> = {
  ios: "iOS",
  android: "Android",
  windows: "Windows",
  macos: "macOS",
  linux: "Linux",
};

/** Бейдж в круглой иконке строки: три знака, больше не влезает. */
export const PLATFORM_BADGE: Record<Platform, string> = {
  ios: "iOS",
  android: "and",
  windows: "win",
  macos: "mac",
  linux: "lin",
};

/** Порядок выбора при выпуске ключа: сначала телефоны, потом десктопы. */
export const PLATFORMS: readonly Platform[] = [
  "ios",
  "android",
  "windows",
  "macos",
  "linux",
];

/** Платформа из адреса приходит строкой: адрес мог набрать человек. */
export function isPlatform(value: string | undefined): value is Platform {
  return PLATFORMS.some((platform) => platform === value);
}
