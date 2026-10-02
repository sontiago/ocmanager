import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const DIST = join(import.meta.dirname, "..", "dist");

function bundleText(): string {
  const assets = join(DIST, "assets");
  return readdirSync(assets)
    .filter((file) => file.endsWith(".js"))
    .map((file) => readFileSync(join(assets, file), "utf8"))
    .join("\n");
}

describe.skipIf(!existsSync(DIST))("production-сборка", () => {
  it("не содержит поддельную initData", () => {
    expect(bundleText()).not.toContain("dev-mock-hash");
  });

  it("не содержит мок-клиента и его сценариев", () => {
    const text = bundleText();
    expect(text).not.toContain("окружение Telegram замокано");
    expect(text).not.toContain("Активный пробный период");
  });

  it("не содержит dev-панели", () => {
    expect(bundleText()).not.toContain("Мок-окружение");
  });

  it("index.html не выставляет X-Frame-Options через meta", () => {
    const html = readFileSync(join(DIST, "index.html"), "utf8");
    expect(html.toLowerCase()).not.toContain("x-frame-options");
  });
});
