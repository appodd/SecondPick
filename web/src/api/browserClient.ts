import { ApiError, request } from "./client";

export interface BrowserJob {
  id: number; kind: "login" | "collection"; task_id: number | null; request_id: number | null;
  retry_of: number | null; query: string; max_pages: number; actions: string[]; listing_ids: number[];
  state: "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  stage: string; error_code: string | null; error_detail: string | null;
  result: { run_ids: number[]; listing_count: number; authenticated?: boolean | null };
  verify_requested: boolean; stop_requested: boolean; created_at: string; completed_at: string | null;
  analysis_operation_id?: number | null;
}
export interface BrowserStatus {
  auth_status: "unknown" | "verified" | "invalid";
  active_job: BrowserJob | null; login_job: BrowserJob | null; max_pages: number; enabled: boolean;
}
export interface BrowserAuditEvent { id: number; event_type: string; created_at: string; metadata: Record<string, string | number | boolean | null> }
export interface BrowserAudit { job_id: number; has_more: boolean; items: BrowserAuditEvent[] }
export const isBrowserActive = (job?: BrowserJob | null) => job?.state === "queued" || job?.state === "running";
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;
function invalid(): never { throw new ApiError({ status: 200, code: "invalid_response", message: "浏览器任务响应不完整，请刷新重试。" }); }
function parseJob(value: unknown): BrowserJob {
  if (!record(value) || !Number.isInteger(value.id) || !["login", "collection"].includes(String(value.kind)) ||
      !["queued", "running", "completed", "failed", "cancelled", "interrupted"].includes(String(value.state)) ||
      typeof value.stage !== "string" || typeof value.query !== "string" || !Number.isInteger(value.max_pages) ||
      !(value.task_id === null || Number.isInteger(value.task_id)) ||
      !(value.request_id === null || Number.isInteger(value.request_id)) ||
      !Array.isArray(value.actions) || !value.actions.every(item => ["search", "detail"].includes(item)) ||
      !Array.isArray(value.listing_ids) || !value.listing_ids.every(Number.isInteger) ||
      !record(value.result) || !Number.isInteger(value.result.listing_count) ||
      !Array.isArray(value.result.run_ids) || !value.result.run_ids.every(Number.isInteger) ||
      !(value.error_detail === null || typeof value.error_detail === "string") ||
      typeof value.stop_requested !== "boolean") invalid();
  return value as unknown as BrowserJob;
}
export const browserApi = {
  async status(): Promise<BrowserStatus> {
    const value = await request<unknown>("/api/browser/status");
    if (!record(value) || !["unknown", "verified", "invalid"].includes(String(value.auth_status)) ||
        !Number.isInteger(value.max_pages) || typeof value.enabled !== "boolean") invalid();
    return { ...value, active_job: value.active_job === null ? null : parseJob(value.active_job),
      login_job: value.login_job === null ? null : parseJob(value.login_job) } as BrowserStatus;
  },
  async login() { return parseJob(await request("/api/setup/xianyu-login", { method: "POST" })); },
  async verify(id: number) { return parseJob(await request(`/api/browser/jobs/${id}/verify`, { method: "POST" })); },
  async cancel(id: number) { return parseJob(await request(`/api/browser/jobs/${id}/cancel`, { method: "POST" })); },
  async audit(id: number): Promise<BrowserAudit> {
    const value = await request<unknown>(`/api/browser/jobs/${id}/audit`);
    if (!record(value) || value.job_id !== id || typeof value.has_more !== "boolean" || !Array.isArray(value.items) ||
      !value.items.every(item => record(item) && Number.isInteger(item.id) && typeof item.event_type === "string" && typeof item.created_at === "string" && record(item.metadata)
        && Object.values(item.metadata).every(field => field === null || typeof field === "string" || typeof field === "boolean" || Number.isInteger(field)))) invalid();
    return value as unknown as BrowserAudit;
  },
  async resumeVerification(id: number) { return parseJob(await request(`/api/browser/jobs/${id}/resume-verification`, { method: "POST" })); },
  async execution(taskId: number, requestId: number): Promise<BrowserJob | null> {
    const value = await request<unknown>(`/api/action-requests/${requestId}/execution?task_id=${taskId}`, undefined, true);
    return value === null ? null : parseJob(value);
  },
  async execute(taskId: number, requestId: number, query: string, maxPages: number, retryOf?: number) {
    return parseJob(await request(`/api/action-requests/${requestId}/execute`, { method: "POST",
      body: JSON.stringify({ task_id: taskId, query, max_pages: maxPages, acknowledge_risk: true, retry_of: retryOf }) }));
  },
};
export const browserStatusQuery = () => ({ queryKey: ["browser-status"], queryFn: browserApi.status, refetchInterval: 2000 });
export const browserStageLabel: Record<string, string> = {
  queued: "等待启动", starting_browser: "正在打开浏览器", waiting_login: "请在浏览器中登录，然后返回验证",
  verifying_login: "正在验证登录", login_not_verified: "未能确认登录，请完成登录后再次验证",
  searching: "正在搜索商品", capturing_detail: "正在采集商品详情", stopping: "正在停止并关闭浏览器",
  waiting_verification: "等待你在浏览器中完成安全验证", verifying_detail: "正在检查验证后的商品详情",
  completed: "已完成", failed: "未完成", cancelled: "已停止", interrupted: "服务重启，任务已中断",
};
