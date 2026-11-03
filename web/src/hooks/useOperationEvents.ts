import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { OperationDetail } from "../api/types";

export type EventSourceFactory = (url: string) => EventSource;
const createSource: EventSourceFactory = url => new EventSource(url);
const names = ["queued", "running", "stage", "preferences_updated", "review_progress", "comparison_saved", "waiting_confirmation", "completed", "failed", "cancelled", "interrupted"];
const stopNames = new Set(["waiting_confirmation", "completed", "failed", "cancelled", "interrupted"]);

export function useOperationEvents(detail?: OperationDetail, factory: EventSourceFactory = createSource) {
  const client = useQueryClient();
  const [status, setStatus] = useState<{ id?: number; stage?: string; reconnecting: boolean }>({ reconnecting: false });
  const operationId = detail?.operation.id;
  const taskId = detail?.operation.task_id;
  const active = detail?.operation.state === "running" || detail?.operation.state === "queued";
  const initialCursor = detail?.last_event_id ?? 0;
  useEffect(() => {
    if (!active || operationId === undefined || typeof EventSource === "undefined" && factory === createSource) return;
    let cursor = initialCursor;
    let disposed = false;
    let source: EventSource;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let retries = 0;
    const refresh = () => {
      void client.invalidateQueries({ queryKey: ["operation", operationId] });
      void client.invalidateQueries({ queryKey: ["task", taskId] });
      void client.invalidateQueries({ queryKey: ["task", taskId, "messages"] });
      void client.invalidateQueries({ queryKey: ["task", taskId, "action-requests"] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
    };
    function connect() {
      if (disposed) return;
      source = factory(`/api/operations/${operationId}/events?after=${cursor}`);
      for (const name of names) source.addEventListener(name, ((event: MessageEvent) => {
        if (disposed) return;
        const id = Number(event.lastEventId);
        if (!Number.isSafeInteger(id) || id <= cursor) return;
        let payload: { stage?: string };
        try { payload = JSON.parse(event.data); } catch { return; }
        cursor = id;
        retries = 0;
        setStatus(previous => ({ id: operationId, stage: typeof payload?.stage === "string" ? payload.stage : previous.stage, reconnecting: false }));
        if (["preferences_updated", "review_progress", "comparison_saved"].includes(name)) refresh();
        if (stopNames.has(name)) { disposed = true; source.close(); refresh(); }
      }) as EventListener);
      source.onerror = () => {
        if (disposed) return;
        source.close();
        setStatus(previous => ({ ...previous, id: operationId, reconnecting: true }));
        refresh();
        timer = setTimeout(connect, Math.min(1000 * 2 ** retries++, 10000));
      };
    }
    connect();
    return () => { disposed = true; clearTimeout(timer); source?.close(); };
    // Keep the cursor within this connection; polling must not reset replay.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operationId, taskId, active, factory, client]);
  return status.id === operationId ? status : { stage: undefined, reconnecting: false };
}
