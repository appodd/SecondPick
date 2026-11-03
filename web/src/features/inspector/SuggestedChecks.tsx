import { useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { queries } from "../../api/queries";
import type { CheckSuggestionRecord } from "../../api/types";

export function SuggestedChecks({ taskId, listingId }: { taskId: number; listingId: number }) {
  const query = useInfiniteQuery(queries.checkSuggestions(taskId, listingId));
  const items = [...new Map(query.data?.pages.flatMap(p => p.items).map(item => [item.id, item]) ?? []).values()];
  return <section aria-label="助手提出的核实建议">
    <h4>助手建议 · 待确认保存</h4>
    <p className="muted">未确认的建议不会加入清单。核对问题后逐项确认；保存不会联系卖家、分析商品或表示核实通过。</p>
    {query.isPending && <p>正在读取助手建议…</p>}
    {query.error && <p role="alert">{query.error.message}<button onClick={() => void query.refetch()}>重试读取建议</button></p>}
    {query.data?.pages[0].total_count === 0 && <p className="muted">暂无助手建议，可继续提问或手动记录。</p>}
    {items.map(item => <Suggestion key={item.id} item={item} />)}
    {query.hasNextPage && <button disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>加载更早建议</button>}
  </section>;
}

function Suggestion({ item }: { item: CheckSuggestionRecord }) {
  const client = useQueryClient();
  const [notice, setNotice] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: ["task", item.task_id, "listing", item.listing_id] });
  const save = useMutation({ mutationFn: () => api.acceptCheckSuggestion(item.task_id, item.listing_id, item.id),
    onSuccess: async result => {
      setNotice(result.reused_existing ? (result.check.effective_state === "dismissed" ? "已有相同问题且已暂不跟进；保留原状态，未重新打开。" : "已有相同问题，沿用原项及其状态；未重复创建。") : "已加入待核实清单，尚未核实。");
      await refresh();
    }, onError: () => { void refresh(); } });
  return <section className="check-item" aria-label={`核实建议：${item.question}`}>
    <strong>{item.question}</strong>
    <p className="message-content">建议理由：{item.reason}</p>
    {item.check_id !== null ? <p>{item.reused_existing ? "已对应已有问题，原状态保留" : "已加入清单，仍需核实"}</p> :
      item.stale ? <p role="status">建议依据的要求或证据已变化，请继续提问后重新核对建议。</p> :
      <button disabled={save.isPending} onClick={() => save.mutate()}>确认保存此问题</button>}
    {notice && <p role="status">{notice}</p>}
    {save.error && <p role="alert">{save.error.message}</p>}
  </section>;
}
