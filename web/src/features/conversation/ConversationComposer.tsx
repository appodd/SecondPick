import { useState } from "react";
import type { CandidateStatementInput } from "../../api/types";

export function ConversationComposer({ disabled, pending, onSend, allowStatements, selectedListingId }: {
  disabled?: boolean; pending?: boolean; allowStatements?: boolean; selectedListingId?: number;
  onSend: (message: string, statement?: CandidateStatementInput) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [purpose, setPurpose] = useState<"chat" | CandidateStatementInput["kind"]>("chat");
  const [target, setTarget] = useState("");
  return <form className="composer-form" onSubmit={async event => {
    event.preventDefault();
    if (disabled || pending || !draft.trim()) return;
    setError("");
    const listingId = Number(target);
    if (purpose !== "chat" && (!Number.isSafeInteger(listingId) || listingId <= 0 || draft.length > 8000)) {
      setError("请指定当前任务的商品编号；证据原文最多 8000 字。"); return;
    }
    try { await onSend(draft, purpose === "chat" ? undefined : { listing_id: listingId, kind: purpose }); setDraft(""); setPurpose("chat"); setTarget(""); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "发送失败，请重试。"); }
  }}>
    <label className="composer-label" htmlFor="conversation-draft">描述需求，或继续询问已有证据</label>
    {allowStatements && <div className="composer-actions composer-binding">
      <label>消息用途 <select aria-label="消息用途" value={purpose} disabled={disabled || pending} onChange={event => {
        setPurpose(event.target.value as typeof purpose); if (event.target.value !== "chat" && !target && selectedListingId) setTarget(String(selectedListingId));
      }}><option value="chat">普通对话</option><option value="seller_reply">转述卖家答复</option><option value="user_observation">本人观察</option></select></label>
      {purpose !== "chat" && <label>证据所属商品编号 <input aria-label="证据所属商品编号" type="number" min={1} step={1} value={target} disabled={disabled || pending} onChange={event => setTarget(event.target.value)} /></label>}
    </div>}
    {purpose !== "chat" && <p className="muted">请粘贴原文并核对商品编号。作为未独立核实的证据保存，不修改购买要求；可在“全部候选”查看编号。</p>}
    <textarea id="conversation-draft" className="conversation-composer" aria-label="对话输入"
      placeholder="例如：预算 5000 元，想找一台适合通勤的二手笔记本…"
      value={draft} maxLength={20000} disabled={disabled || pending}
      onChange={event => setDraft(event.target.value)} rows={3} />
    <div className="composer-actions"><span className="muted">回答完整后显示 · 采集需单独确认并执行</span>
      <button className="primary-button" disabled={disabled || pending || !draft.trim()} type="submit">{pending ? "发送中…" : "发送"}</button></div>
    {error && <p className="scoped-error" role="alert">{error}</p>}
  </form>;
}
