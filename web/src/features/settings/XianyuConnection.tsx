import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { browserApi, browserStageLabel, browserStatusQuery, isBrowserActive } from "../../api/browserClient";

export function XianyuConnection() {
  const client = useQueryClient();
  const status = useQuery(browserStatusQuery());
  const job = status.data?.login_job;
  const active = isBrowserActive(job);
  const action = useMutation({ mutationFn: (kind: "login" | "verify" | "cancel") =>
    kind === "login" ? browserApi.login() : kind === "verify" ? browserApi.verify(job!.id) : browserApi.cancel(job!.id),
    onSettled: () => client.invalidateQueries({ queryKey: ["browser-status"] }),
  });
  return <div className="xianyu-connection">
    <p>登录状态：{status.data?.auth_status === "verified" ? "已验证" : status.data?.auth_status === "invalid" ? "需要重新验证" : "尚未验证"}</p>
    <p className="muted">打开本机浏览器完成闲鱼登录。登录信息保存在本机；验证后可返回研究任务执行采集。</p>
    {job && <p role="status">{browserStageLabel[job.stage] ?? job.stage}{job.error_detail ? `：${job.error_detail}` : ""}</p>}
    <div className="action-request__buttons">
      {!active && <button className="secondary-button" disabled={action.isPending || !status.data?.enabled || !!status.data?.active_job}
        onClick={() => action.mutate("login")}>打开闲鱼登录窗口</button>}
      {active && <><button className="primary-button" disabled={action.isPending || job?.state !== "running" || !["waiting_login", "login_not_verified"].includes(job.stage)}
        onClick={() => action.mutate("verify")}>我已登录，验证</button>
        <button disabled={action.isPending || job?.stop_requested} onClick={() => action.mutate("cancel")}>停止登录</button></>}
    </div>
    {status.data && !status.data.enabled && <p>请在配置中允许登录，并在偏好设置中启用闲鱼。</p>}
    {(status.error || action.error) && <p className="scoped-error" role="alert">{action.error?.message ?? status.error?.message}</p>}
  </div>;
}
