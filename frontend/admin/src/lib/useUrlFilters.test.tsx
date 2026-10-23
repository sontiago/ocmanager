import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { useUrlFilters } from "./useUrlFilters";

function setup(initial: string) {
  let search = "";
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={[initial]}>
        <Spy />
        {children}
      </MemoryRouter>
    );
  }
  function Spy() {
    search = useLocation().search;
    return null;
  }
  const hook = renderHook(() => useUrlFilters(["q", "status"] as const), { wrapper: Wrapper });
  return { hook, search: () => search };
}

test("changing_filter_resets_offset", () => {
  const { hook, search } = setup("/?offset=100&q=a");
  expect(hook.result.current.offset).toBe(100);
  act(() => hook.result.current.set({ q: "bob" }));
  expect(hook.result.current.offset).toBe(0);
  expect(search()).toBe("?q=bob");
});

test("empty_values_are_not_written_to_url", () => {
  const { hook, search } = setup("/?q=a&status=active");
  act(() => hook.result.current.set({ q: "" , status: undefined }));
  expect(search()).toBe("");
  expect(hook.result.current.values).toEqual({ q: undefined, status: undefined });
});

test("setOffset_keeps_filters", () => {
  const { hook, search } = setup("/?q=a");
  act(() => hook.result.current.setOffset(50));
  expect(search()).toBe("?q=a&offset=50");
});

test("garbage_offset_becomes_zero", () => {
  const { hook } = setup("/?offset=-5");
  expect(hook.result.current.offset).toBe(0);
});
