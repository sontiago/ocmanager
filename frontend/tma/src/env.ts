export type ApiMode = "mock" | "http";

export interface AppEnv {
  apiMode: ApiMode;
  apiBaseUrl: string;
  devPanel: boolean;
  supportHandle: string;
}

type RawEnv = Record<string, string | undefined>;

export function readEnv(raw: RawEnv): AppEnv {
  const mode = raw.VITE_API_MODE ?? "mock";
  if (mode !== "mock" && mode !== "http") {
    throw new Error(
      `VITE_API_MODE должен быть "mock" или "http", получено: ${mode}`,
    );
  }

  return {
    apiMode: mode,
    apiBaseUrl: (raw.VITE_API_BASE_URL ?? "/api").replace(/\/+$/, ""),
    devPanel: raw.VITE_DEV_PANEL === "true",
    supportHandle: raw.VITE_SUPPORT_HANDLE ?? "@ocmanager_help",
  };
}

export const env: AppEnv = readEnv(import.meta.env as RawEnv);
