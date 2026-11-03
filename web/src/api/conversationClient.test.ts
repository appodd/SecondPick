import { afterEach, expect, it, vi } from "vitest";
import { api } from "./client";

const operation = { id: 2, task_id: 1, state: "running", error_code: null, error_detail: null };
afterEach(() => vi.unstubAllGlobals());

it("sends only the message and rejects malformed nested operation data", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: {}, operation: { ...operation, state: "arbitrary" } })));
  vi.stubGlobal("fetch", fetcher);
  await expect(api.sendMessage(1, "Camera")).rejects.toMatchObject({ code: "invalid_response" });
  expect(fetcher).toHaveBeenCalledWith("/api/tasks/1/messages", expect.objectContaining({ method: "POST", body: '{"message":"Camera"}' }));
});

it("validates action history and preserves pagination cursors", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [{ id: 3, task_id: 1, operation_id: 2, summary: "Search", risk: "Access", listing_ids: [], actions: ["buy"], state: "pending" }], has_more: false, next_before_id: null }))));
  await expect(api.getActionRequests(1)).rejects.toMatchObject({ code: "invalid_response" });
});

it("loads durable operation state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ operation, last_event_id: 4, action_request: null }))));
  expect((await api.getOperation(2)).operation.state).toBe("running");
});
