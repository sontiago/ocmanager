import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders_router_outlet", async () => {
  // Сессии нет: без сети fetch падает, приложение показывает форму входа.
  vi.stubGlobal("fetch", async () => new Response(null, { status: 401 }));
  render(<App />);
  expect(await screen.findByRole("main")).toBeInTheDocument();
  vi.unstubAllGlobals();
});
