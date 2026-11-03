import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { BrowserJob } from "../../api/browserClient";
import { CollectionAudit } from "./CollectionAudit";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const job = { id: 8, state: "running" } as BrowserJob;
const challenge = { id: 1, event_type: "verification_required", created_at: "2026-10-07T06:00:00+00:00",
  metadata: { operation: "detail", listing_id: 4721, page_index: 2, requested_pages: 3, completed_pages: 1 } };

it("loads only when expanded and fetches terminal records when the job ends", async () => {
  let reads = 0;
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ job_id: 8, has_more: false, items: ++reads > 1 ?
    [challenge, { id: 2, event_type: "job_finished", created_at: "2026-10-07T06:10:00+00:00", metadata: { state: "failed", error_code: "browser_timeout" } }] : [challenge] })));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><CollectionAudit job={job} /></QueryClientProvider>);
  expect(fetcher).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("访问与验证记录"));
  expect(await screen.findByText(/商品 #4721 · 第 2\/3 条 · 已完成 1 条/)).toBeInTheDocument();
  view.rerender(<QueryClientProvider client={client}><CollectionAudit job={{ ...job, state: "failed" }} /></QueryClientProvider>);
  expect(await screen.findByText(/等待或采集超时/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/browser/jobs/8/audit", expect.anything());
});

it("retries failures and makes absence of historical audit records explicit", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response("{}", { status: 503 }))
    .mockResolvedValue(new Response(JSON.stringify({ job_id: 8, has_more: false, items: [] })));
  vi.stubGlobal("fetch", fetcher);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <CollectionAudit job={{ ...job, state: "completed" }} /></QueryClientProvider>);
  await userEvent.click(screen.getByText("访问与验证记录"));
  expect(await screen.findByRole("alert")).toHaveTextContent("记录暂时无法加载");
  await userEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByText(/较早执行未采集这些日志/)).toBeInTheDocument();
});
