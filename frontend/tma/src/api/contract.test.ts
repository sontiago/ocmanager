import { beforeEach } from "vitest";
import { runContractSuite } from "../test/contract.suite";
import { createMockClient } from "./mock/client";
import { resetStore, setLatency } from "./mock/store";

beforeEach(() => {
  sessionStorage.clear();
  resetStore("active");
  setLatency(0);
});

runContractSuite("mock", async () => createMockClient());