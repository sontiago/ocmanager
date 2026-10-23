import { act, renderHook } from "@testing-library/react";
import { FakeEventSource } from "../test/FakeEventSource";
import { useEventSource } from "./useEventSource";

beforeEach(() => {
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => vi.unstubAllGlobals());

const es = (i = 0) => FakeEventSource.instances[i];

test("does_not_connect_without_url", () => {
  renderHook(() => useEventSource(null, { max: 10 }));
  expect(FakeEventSource.instances).toHaveLength(0);
});

test("collects_messages_and_reports_open", () => {
  const { result } = renderHook(() => useEventSource("/x", { max: 10 }));
  expect(result.current.state).toBe("connecting");
  act(() => es().emit("open"));
  act(() => es().emit("message", "line 1"));
  expect(result.current.state).toBe("open");
  expect(result.current.lines).toEqual(["line 1"]);
});

test("closes_on_unmount", () => {
  const { unmount } = renderHook(() => useEventSource("/x", { max: 10 }));
  unmount();
  expect(es().closed).toBe(true);
});

test("closes_previous_on_url_change", () => {
  const { rerender } = renderHook(({ url }) => useEventSource(url, { max: 10 }), {
    initialProps: { url: "/a" as string | null },
  });
  rerender({ url: "/b" });
  expect(es(0).closed).toBe(true);
  expect(es(1).url).toBe("/b");
  rerender({ url: null });
  expect(es(1).closed).toBe(true);
});

test("keeps_only_last_max_lines", () => {
  const { result } = renderHook(() => useEventSource("/x", { max: 3 }));
  act(() => {
    for (let i = 1; i <= 5; i++) es().emit("message", `l${i}`);
  });
  expect(result.current.lines).toEqual(["l3", "l4", "l5"]);
});

test("named_error_event_sets_error_state", () => {
  const { result } = renderHook(() => useEventSource("/x", { max: 10 }));
  act(() => es().emit("error", "node unavailable"));
  expect(result.current.state).toBe("error");
  expect(result.current.error).toBe("node unavailable");
  expect(es().closed).toBe(true);
});

test("connection_error_closes_and_does_not_reconnect", () => {
  const { result } = renderHook(() => useEventSource("/x", { max: 10 }));
  act(() => es().emit("error"));
  expect(result.current.state).toBe("error");
  expect(es().closed).toBe(true);
  expect(FakeEventSource.instances).toHaveLength(1);
});

test("clear_empties_lines", () => {
  const { result } = renderHook(() => useEventSource("/x", { max: 10 }));
  act(() => es().emit("message", "a"));
  act(() => result.current.clear());
  expect(result.current.lines).toEqual([]);
});
