import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { CandidateStatementBinding, CandidateStatementInput, StatementChange } from "../../api/types";

export function StatementBindingControls({ taskId, binding, onSelectListing, locked = false }: {
  taskId: number; binding: CandidateStatementBinding; onSelectListing: (id: number) => void; locked?: boolean;
}) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [target, setTarget] = useState(String(binding.listing_id));
  const [kind, setKind] = useState<CandidateStatementInput["kind"]>(binding.kind);
  const [notice, setNotice] = useState("");
  const mutation = useMutation({
    mutationFn: (change: StatementChange) => api.changeStatement(taskId, binding.id, change),
    onSuccess: async () => {
      setEditing(false);
      setNotice("已保存；受影响的评估需要按当前证据重新分析。");
      await client.invalidateQueries({ queryKey: ["task", taskId] });
    },
    onError: () => { void client.invalidateQueries({ queryKey: ["task", taskId] }); },
  });
  const withdrawn = binding.status === "withdrawn";
  const listingId = Number(target);
  return <div className="statement-controls">
    <p className="muted">{withdrawn ? "已撤回的补充" : binding.kind === "seller_reply" ? "用户转述卖家答复" : "用户本人观察"}
      {` · 商品 #${binding.listing_id} · 未经独立核实`}
      {binding.original_listing_id && binding.original_listing_id !== binding.listing_id && ` · 原绑定 #${binding.original_listing_id}`}
      <button onClick={() => onSelectListing(binding.listing_id)}>查看绑定商品证据</button>
    </p>
    {withdrawn ? <p className="muted">原文保留，不再作为当前证据；需要恢复请重新发送补充。</p> : <>
      <button disabled={mutation.isPending || locked} onClick={() => {
        setTarget(String(binding.listing_id)); setKind(binding.kind); setEditing(true); mutation.reset(); setNotice("");
      }}>更正归属</button>
      <button disabled={mutation.isPending || locked} onClick={() => mutation.mutate({ action: "withdraw", expected_revision_id: binding.revision_id ?? 0 })}>撤回此补充</button>
      {locked && <p className="muted">请先结束采集或处理待确认请求，再更正补充证据。</p>}
      {editing && <form className="composer-binding" onSubmit={event => {
        event.preventDefault();
        if (!locked && !mutation.isPending && Number.isSafeInteger(listingId) && listingId > 0) mutation.mutate({ action: "rebind", expected_revision_id: binding.revision_id ?? 0, listing_id: listingId, kind });
      }}>
        <label>更正后的商品编号<input type="number" min="1" step="1" value={target} onChange={event => setTarget(event.target.value)} /></label>
        <label>补充类型<select value={kind} onChange={event => setKind(event.target.value as CandidateStatementInput["kind"])}>
          <option value="seller_reply">用户转述卖家答复</option><option value="user_observation">用户本人观察</option>
        </select></label>
        <button disabled={mutation.isPending || locked || !Number.isSafeInteger(listingId) || listingId <= 0}>保存更正</button>
        <button type="button" disabled={mutation.isPending} onClick={() => setEditing(false)}>取消</button>
      </form>}
    </>}
    {notice && <p role="status">{notice}</p>}
    {mutation.error && <p role="alert">{mutation.error.message}</p>}
  </div>;
}
