import { request } from "./client";

export type MonitorState = "waiting" | "running" | "paused" | "stopped" | "needs_attention";
export interface MonitorScope {
  keyword: string; max_pages: number; max_items: number; interval_seconds: number;
  max_rounds: number; collect_seller_profiles: boolean;
}
export interface Monitor extends MonitorScope {
  id: number; task_id: number; state: MonitorState; desired_state: "paused" | "stopped" | null;
  rounds: number; imported: number; next_run_at: string | null; error_code: string | null;
  updated_at: string;
  result: {
    candidate_pool_count?: number; collection?: { raw_saved?: number; seller_records_saved?: number; seller_profile_failures?: number };
    imported?: number; search_cards?: { imported?: number }; price_observations?: { imported?: number };
    sync_pending?: boolean; diagnostics_available?: boolean;
    worker_status?: { phase: string; error_code: string | null };
    retention?: { warning: boolean };
  };
}
export interface MonitorPage { enabled: boolean; platform_enabled: boolean; candidate_pool_count: number; items: Monitor[] }
export interface MonitorReadiness { ready: boolean; checked_at: string; checks: { code: string; ok: boolean }[] }
export interface DiagnosticPage {
  items: { id: number; phase: string; code: string; created_at: string; counts: Record<string, number> }[];
  has_more: boolean; next_before_id: number | null;
}
export interface ConsolePage {
  items: { at: string; text: string }[]; rounds: { id: string; updated_at: string }[];
  round_id: string | null; next_before: number | null; has_more: boolean; capture_enabled: boolean;
  max_bytes: number; max_rounds: number; read_error?: boolean;
}
const path = (taskId: number) => `/api/tasks/${taskId}/monitors`;
export const monitorApi = {
  environment: () => request<{ result: MonitorReadiness | null }>("/api/monitor-engine/check"),
  checkEnvironment: () => request<MonitorReadiness>("/api/monitor-engine/check", { method: "POST" }),
  logs: (taskId: number, id: number, roundId?: string, before?: number) => {
    const params = new URLSearchParams({ limit: "100" });
    if (roundId) params.set("round_id", roundId);
    if (before !== undefined) params.set("before", String(before));
    return request<ConsolePage>(`${path(taskId)}/${id}/logs?${params}`);
  },
  list: async (taskId: number) => {
    const page = await request<MonitorPage>(path(taskId));
    if (typeof page.enabled !== "boolean" || !Array.isArray(page.items) || !Number.isSafeInteger(page.candidate_pool_count)) {
      throw new Error("监控状态数据不完整");
    }
    return page;
  },
  create: (taskId: number, scope: MonitorScope) => request<Monitor>(path(taskId), { method: "POST", body: JSON.stringify({ ...scope, confirmed: true }) }),
  control: (taskId: number, id: number, action: "pause" | "resume" | "stop") => request<Monitor>(`${path(taskId)}/${id}/${action}`, { method: "POST" }),
  events: (taskId: number, id: number, cursor?: number) => request<DiagnosticPage>(`${path(taskId)}/${id}/events?limit=20${cursor ? `&before_id=${cursor}` : ""}`),
};

export const monitorErrors: Record<string, string> = {
  service_restarted: "服务已重启，监控已暂停。核对原范围后可恢复。",
  login_required: "登录状态不可用。请到设置页重新登录并验证，再恢复监控。",
  verification_required: "闲鱼要求安全验证，本次监控已暂停。请到设置页完成登录验证后恢复。",
  engine_not_configured: "监控引擎尚未配置完成，请完成本地引擎配置后恢复。",
  engine_version_unsupported: "采集引擎版本不兼容，需要检查本地引擎版本。",
  engine_timeout: "本轮采集超时，已保存的数据保留。可恢复原范围继续采集。",
  engine_paused: "连续失败触发采集保护，等待保护期结束或重新验证登录后再恢复。",
  engine_sync_failed: "数据同步未完成，源记录和已入库商品保留，请检查后恢复。",
  engine_save_failed: "采集记录保存失败，已入库商品保留，请检查本地存储。",
  engine_pipeline_failed: "采集处理未完成，已保存的数据保留，请检查后恢复。",
  engine_dependencies_missing: "采集环境缺少依赖，请修复本地引擎环境。",
  engine_timezone_missing: "采集环境缺少时区数据，请修复本地引擎环境。",
  engine_failed: "本轮采集未完成，已保存的数据保留，可查看运行记录。",
  cancelled: "本轮采集已中止，已保存的数据保留。",
};
export const monitorPhases: Record<string, string> = {
  bootstrap: "准备采集", timezone_check: "检查采集环境", engine_import: "加载采集引擎",
  collecting: "正在采集", completed: "采集程序已返回",
};
