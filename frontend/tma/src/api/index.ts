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

  // import.meta.env.VITE_API_MODE подставляется сборщиком как константа: при VITE_API_MODE=http
  // условие ложно статически, и мок-клиент с фикстурами в бандл не попадает (src/build.test.ts).
  // env.apiMode для этого не годится — он вычисляется в рантайме.
  if (import.meta.env.VITE_API_MODE !== "http") {
    const { createMockClient } = await import("./mock/client");
    const { resetStore } = await import("./mock/store");
    resetStore();
    return createMockClient();
  }
  throw new Error("mock-клиент не включён в эту сборку");
}

export type { ApiClient } from "./contract";
