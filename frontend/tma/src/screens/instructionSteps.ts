import type { Platform } from "../api/types";
import type { MessageKey } from "../i18n/ru";

/** Штатный клиент под каждую систему. null — ставится пакетным менеджером. */
export const STORE_LINKS: Record<Platform, string | null> = {
  ios: "https://apps.apple.com/app/cisco-secure-client/id1135064690",
  android:
    "https://play.google.com/store/apps/details?id=com.cisco.anyconnect.vpn.android.avf",
  windows: "https://openconnect.github.io/openconnect-gui/",
  macos: "https://openconnect.github.io/openconnect-gui/",
  linux: null,
};

/**
 * Ключи перечислены руками, а не собраны шаблоном `instructions.${p}.${n}`:
 * собранная строка потребовала бы приведения к MessageKey, и опечатка или
 * забытый перевод дожили бы до экрана вместо ошибки компиляции.
 */
export const STEP_KEYS: Record<Platform, readonly MessageKey[]> = {
  ios: [
    "instructions.ios.1",
    "instructions.ios.2",
    "instructions.ios.3",
    "instructions.ios.4",
  ],
  android: [
    "instructions.android.1",
    "instructions.android.2",
    "instructions.android.3",
    "instructions.android.4",
  ],
  windows: [
    "instructions.windows.1",
    "instructions.windows.2",
    "instructions.windows.3",
    "instructions.windows.4",
  ],
  macos: [
    "instructions.macos.1",
    "instructions.macos.2",
    "instructions.macos.3",
    "instructions.macos.4",
  ],
  linux: [
    "instructions.linux.1",
    "instructions.linux.2",
    "instructions.linux.3",
    "instructions.linux.4",
  ],
};
