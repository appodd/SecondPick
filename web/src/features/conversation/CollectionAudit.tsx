import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { browserApi, isBrowserActive, type BrowserAuditEvent, type BrowserJob } from "../../api/browserClient";

const labels: Record<string, string> = { page_attempt: "尝试采集页面", verification_required: "出现安全验证", manual_continue: "已点击继续",
  verification_check: "检查验证结果", page_completed: "商品详情已保存", search_completed: "搜索已结束", job_finished: "本次执行结束", login_check: "检查登录结果" };
const operations: Record<string, string> = { detail: "商品详情", search: "搜索", login: "登录" };
const states: Record<string, string> = { completed: "完成", failed: "未完成", cancelled: "已停止", interrupted: "服务重启中断" };
const reasons: Record<string, string> = { access_blocked: "平台验证或访问受限", login_required: "登录已失效", pagination_incomplete: "分页未完成", browser_timeout: "等待或采集超时", search_cooldown: "搜索冷却中", verification_closed: "验证窗口已关闭", detail_unavailable: "未读取到商品详情", service_restarted: "服务已重启" };
function description(event: BrowserAuditEvent) {
  const data = event.metadata;
  return [operations[String(data.operation)], data.listing_id ? `商品 #${data.listing_id}` : null,
    data.page_index ? `第 ${data.page_index}/${data.requested_pages} 条` : null,
    typeof data.completed_pages === "number" ? `已完成 ${data.completed_pages} 条` : null,
    typeof data.scheduled_delay_ms === "number" ? `本页等待 ${(data.scheduled_delay_ms / 1000).toFixed(1)} 秒` : null,
    typeof data.since_previous_attempt_ms === "number" ? `距上次页面尝试 ${(data.since_previous_attempt_ms / 1000).toFixed(1)} 秒` : null,
    typeof data.recent_attempt_count_30m === "number" ? `近 30 分钟尝试 ${data.recent_attempt_count_30m} 次` : null,
    typeof data.captured_pages === "number" ? `已收到 ${data.captured_pages} 页搜索响应` : null,
    data.stop_reason ? `停止原因：${reasons[String(data.stop_reason)] ?? data.stop_reason}` : null,
    typeof data.cleared === "boolean" ? data.cleared ? "检查通过" : "尚未通过" : null,
    data.state ? states[String(data.state)] ?? String(data.state) : null,
    data.error_code ? reasons[String(data.error_code)] ?? String(data.error_code) : null,
  ].filter(Boolean).join(" · ");
}
export function CollectionAudit({ job }: { job: BrowserJob }) {
  const [open, setOpen] = useState(false);
  const events = useQuery({ queryKey: ["browser-audit", job.id, job.state], queryFn: () => browserApi.audit(job.id), enabled: open,
    refetchInterval: open && isBrowserActive(job) ? 2000 : false });
  return <details className="collection-audit" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>访问与验证记录</summary>
    {events.isPending && <p>加载记录…</p>}
    {events.error && <p role="alert">记录暂时无法加载。<button onClick={() => void events.refetch()}>重试</button></p>}
    {events.data?.has_more && <p className="muted">显示最近 100 条记录。</p>}
    {events.data && !events.data.items.length && <p className="muted">本次执行暂无记录；较早执行未采集这些日志。</p>}
    <ol>{events.data?.items.map(event => <li key={event.id}><div><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleTimeString("zh-CN")}</time> {labels[event.event_type] ?? event.event_type}</div><p>{description(event)}</p></li>)}</ol>
  </details>;
}
