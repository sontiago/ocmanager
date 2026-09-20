import { env } from "../env";
import { getInitDataRaw } from "../telegram/auth";
import type { ApiClient } from "./contract";
import { createHttpClient } from "./http";

export function createApiClient(): ApiClient {
  if (env.apiMode === "http") {
    return createHttpClient({
      baseUrl: env.apiBaseUrl,
      getInitDataRaw,
    });
  }

  // Синхронный require невозможен, поэтому мок подключается лениво:
  // в production-бандле этой ветки не остаётся.
  throw new Error(
    "createApiClient(): режим mock требует createApiClientAsync()",
  );
}

export async function createApiClientAsync(): Promise<ApiClient> {
  if (env.apiMode === "http") return createApiClient();

  const { createMockClient } = await import("./mock/client");
  const { resetStore } = await import("./mock/store");
  resetStore();
  return createMockClient();
}

export type { ApiClient } from "./contract";
