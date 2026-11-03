import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useOperationEvents } from "./useOperationEvents";

it("refreshes saved requirements without closing the running operation", async () => {
  const listeners = new Map<string, (event: MessageEvent) => void>();
  const close = vi.fn();
  const factory = vi.fn(() => ({ addEventListener: (name: string, fn: (event: MessageEvent) => void) => listeners.set(name, fn), close } as unknown as EventSource));
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { unmount } = renderHook(() => useOperationEvents({ operation: { id: 2, task_id: 8, state: "running", error_code: null, error_detail: null }, last_event_id: 3, action_request: null }, factory), { wrapper });
  await waitFor(() => expect(listeners.has("preferences_updated")).toBe(true));
  act(() => listeners.get("preferences_updated")!(new MessageEvent("preferences_updated", { lastEventId: "4", data: '{"revision_id":1}' })));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["task", 8] });
  expect(close).not.toHaveBeenCalled();
  const count = invalidate.mock.calls.length;
  act(() => listeners.get("preferences_updated")!(new MessageEvent("preferences_updated", { lastEventId: "4", data: '{"revision_id":1}' })));
  expect(invalidate.mock.calls).toHaveLength(count);
  unmount();
});

it("replays from durable cursor, deduplicates events and closes on completion", async () => {
  const listeners = new Map<string, (event: MessageEvent) => void>();
  const close = vi.fn();
  const factory = vi.fn(() => ({ addEventListener: (name: string, fn: (event: MessageEvent) => void) => listeners.set(name, fn), close, onerror: null } as unknown as EventSource));
  const client = new QueryClient();
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result, unmount } = renderHook(() => useOperationEvents({ operation: { id: 2, task_id: 8, state: "running", error_code: null, error_detail: null }, last_event_id: 3, action_request: null }, factory), { wrapper });
  await waitFor(() => expect(factory).toHaveBeenCalledWith("/api/operations/2/events?after=3"));
  act(() => {
    listeners.get("stage")!(new MessageEvent("stage", { lastEventId: "4", data: '{"stage":"analyzing_evidence"}' }));
    listeners.get("stage")!(new MessageEvent("stage", { lastEventId: "3", data: '{"stage":"starting_codex"}' }));
  });
  expect(result.current.stage).toBe("analyzing_evidence");
  act(() => listeners.get("completed")!(new MessageEvent("completed", { lastEventId: "5", data: "{}" })));
  expect(close).toHaveBeenCalled();
  unmount();
});

it("reconnects from the last received ID and closes the old connection on task switch", async () => {
  vi.useFakeTimers();
  const sources: { close: ReturnType<typeof vi.fn>; onerror: (() => void) | null; listeners: Map<string, (event: MessageEvent) => void> }[] = [];
  const factory = vi.fn(() => {
    const source = { close: vi.fn(), onerror: null as (() => void) | null, listeners: new Map<string, (event: MessageEvent) => void>(), addEventListener(name: string, fn: (event: MessageEvent) => void) { this.listeners.set(name, fn); } };
    sources.push(source);
    return source as unknown as EventSource;
  });
  const client = new QueryClient();
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { rerender, unmount } = renderHook(({ id }) => useOperationEvents({ operation: { id, task_id: id, state: "running", error_code: null, error_detail: null }, last_event_id: 3, action_request: null }, factory), { wrapper, initialProps: { id: 2 } });
  try {
    act(() => {
      sources[0].listeners.get("stage")!(new MessageEvent("stage", { lastEventId: "7", data: '{"stage":"analyzing_evidence"}' }));
      sources[0].onerror!();
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(factory).toHaveBeenLastCalledWith("/api/operations/2/events?after=7");
    rerender({ id: 9 });
    expect(sources[1].close).toHaveBeenCalledOnce();
    expect(factory).toHaveBeenLastCalledWith("/api/operations/9/events?after=3");
  } finally { unmount(); vi.useRealTimers(); }
});
