import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { monitorApi, type Monitor } from "../../api/monitorClient";

export function MonitorConsole({ monitor, initialRound = "", onRoundChange }: { monitor: Monitor; initialRound?: string; onRoundChange?: (round: string) => void }) {
  const [round, setRound] = useState(initialRound);
  const [before, setBefore] = useState<number>();
  const [refresh, setRefresh] = useState(true);
  const [follow, setFollow] = useState(true);
  const pane = useRef<HTMLPreElement>(null);
  const previousState = useRef(monitor.state);
  const query = useQuery({ queryKey: ["monitor-console", monitor.task_id, monitor.id, round, before],
    queryFn: () => monitorApi.logs(monitor.task_id, monitor.id, round || undefined, before),
    refetchInterval: refresh && !round && before === undefined && monitor.state === "running" ? 2000 : false });
  function changeRound(value: string) { setRound(value); onRoundChange?.(value); setBefore(undefined); }
  useEffect(() => {
    if (onRoundChange && initialRound !== round) { setRound(initialRound); setBefore(undefined); }
  }, [initialRound]);
  useEffect(() => {
    if (previousState.current !== monitor.state) {
      previousState.current = monitor.state;
      void query.refetch();
    }
  }, [monitor.state, query.refetch]);
  useEffect(() => {
    if (pane.current && (round || before !== undefined)) pane.current.scrollTop = 0;
    else if (follow && pane.current) pane.current.scrollTop = pane.current.scrollHeight;
  }, [query.dataUpdatedAt, follow, before, round]);
  const data = query.data;
  return <section className="monitor-console" aria-label="采集实时日志">
    <div className="monitor-actions">
      <label>采集轮次<select aria-label="日志采集轮次" value={round} onChange={e => changeRound(e.target.value)}>
        <option value="">最新一轮</option>
        {round && data && !data.rounds.some(item => item.id === round) && <option value={round}>所选轮次 {round.slice(0, 8)}（当前不可用）</option>}
        {data?.rounds.map(r => <option key={r.id} value={r.id}>{new Date(r.updated_at).toLocaleString("zh-CN")} · {r.id.slice(0, 8)}</option>)}
      </select></label>
      <label><input type="checkbox" checked={refresh} onChange={e => setRefresh(e.target.checked)} />自动刷新日志</label>
      <label><input type="checkbox" checked={follow} onChange={e => setFollow(e.target.checked)} />跟随最新输出</label>
      <button disabled={query.isFetching} onClick={() => void query.refetch()}>刷新日志</button>
    </div>
    <p className="muted">{data ? `保留最近 ${data.max_rounds} 轮，每轮约 ${Math.round(data.max_bytes / 1024 / 1024)} MiB；` : "正在读取日志保留范围；"}显示最近 100 行，可查看更早输出。凭据字段和网址参数会过滤。日志内容不作为商品已核实的证据。</p>
    {query.isPending && <p>加载采集日志…</p>}
    {query.error && <p className="scoped-error" role="alert">{query.error.message}</p>}
    {data && !data.round_id && <p>{round ? "所选轮次日志不可用，可能已超出保留范围；可切换到其他轮次。" : "该监控还没有控制台日志；以前未保存的输出无法补回。"}</p>}
    {data && !data.capture_enabled && <p>当前配置已关闭日志采集，已有日志仍可查看。</p>}
    {data?.read_error && <p>日志暂时无法读取，请刷新重试。</p>}
    {data?.round_id && <pre ref={pane} tabIndex={0} role="log" aria-label="采集日志输出" aria-live="off">
      {data.items.map(row => `[${new Date(row.at).toLocaleTimeString("zh-CN", { hour12: false })}] ${row.text}`).join("\n") || (data.read_error ? "日志读取失败，请重试。" : monitor.state === "running" && !round ? "等待采集器输出…" : "该轮次没有已保存的日志输出。")}
    </pre>}
    <div className="monitor-actions">
      {data?.has_more && data.next_before !== null && <button disabled={query.isFetching} onClick={() => { changeRound(data.round_id ?? ""); setBefore(data.next_before ?? undefined); }}>查看更早日志</button>}
      {(before !== undefined || round) && <button onClick={() => changeRound("")}>回到最新日志</button>}
      {before !== undefined && <span className="muted">正在查看历史片段，自动刷新已暂停。</span>}
      {round && before === undefined && <span className="muted">正在查看指定历史轮次，自动刷新已暂停。</span>}
    </div>
  </section>;
}
