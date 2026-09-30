import { describe } from "vitest";
import { runContractSuite } from "../test/contract.suite";
import { createHttpClient } from "./http";

const BASE_URL = process.env.TMA_E2E_BASE_URL;

// Без переменной окружения набор пропускается: обычный `npm test` не зависит от бэкенда.
// Запуск против живого бэкенда — см. README, раздел «Проверка против бэкенда».
if (BASE_URL) {
  runContractSuite("http", async () =>
    createHttpClient({
      baseUrl: BASE_URL,
      getInitDataRaw: () => process.env.TMA_E2E_INIT_DATA,
    }),
  );
} else {
  describe.skip("контракт ApiClient: http (нужен TMA_E2E_BASE_URL)", () => {});
}
