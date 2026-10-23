import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders_router_outlet", () => {
  render(<App />);
  expect(screen.getByRole("main")).toBeInTheDocument();
});
