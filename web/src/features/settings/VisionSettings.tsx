import { useEffect, useRef, useState, type FormEvent } from "react";
import { Eye, LockKeyhole, Pencil, Save, Plus, RefreshCw, Check, Trash2 } from "lucide-react";
import { ApiError, request } from "../../api/client";

export type VisionConfig = { provider: string; model: string; timeout_seconds: number; max_output_tokens: number };
export type VisionProfile = VisionConfig & { id: string; revision: number; current: boolean; key_configured: boolean; capability_declared: boolean;
  verification: { state: string; checked_at?: string; message?: string }; imported?: boolean };
export type VisionStatus = { revision: number; enabled: boolean; current_id: string | null; storage: string; profiles: VisionProfile[];
  providers: { id: string; endpoint: string; models: string[] }[]; legacy_requires_verification?: boolean;
  operation?: { state: string; kind: string } | null };
const defaults: VisionConfig = { provider: "deepseek", model: "deepseek-flash", timeout_seconds: 300, max_output_tokens: 3000 };
const providerName = (id: string) => id === "deepseek" ? "DeepSeek" : id;
function fields(p: VisionConfig): VisionConfig { return { provider: p.provider, model: p.model, timeout_seconds: p.timeout_seconds, max_output_tokens: p.max_output_tokens }; }
function verificationLabel(state: string) { return ({ verified: "连接已验证", failed: "验证失败", verifying: "正在验证" } as Record<string,string>)[state] ?? "尚未验证"; }

export function VisionSettings() {
  const [status, setStatus] = useState<VisionStatus>(), [form, setForm] = useState<VisionConfig>();
  const [editing, setEditing] = useState<string | null>(null), [pending, setPending] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const keyInput = useRef<HTMLInputElement>(null), busy = useRef(false), mounted = useRef(false), editor = useRef<HTMLFormElement>(null);
  function clearKey() { if (keyInput.current) keyInput.current.value = ""; }
  async function load() { const value = await request<VisionStatus>("/api/vision/profiles"); if (mounted.current) setStatus(value); return value; }
  useEffect(() => { mounted.current = true; void load().catch(() => { if (mounted.current) setError("无法读取视觉模型配置，请稍后重试。"); });
    return () => { mounted.current = false; clearKey(); }; }, []);
  function open(p?: VisionProfile) {
    clearKey(); setEditing(p?.id ?? "new"); setForm(p ? fields(p) : { ...defaults, provider: status?.providers[0]?.id ?? defaults.provider, model: status?.providers[0]?.models[0] ?? defaults.model }); setError(""); setNotice("");
  }
  useEffect(() => { if (editing) editor.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" }); }, [editing]);
  useEffect(() => {
    if (status?.operation?.state !== "running" || pending) return;
    const timer = window.setTimeout(() => { void load().catch(() => setError("状态读取失败，请刷新核对。")); }, 1500);
    return () => window.clearTimeout(timer);
  }, [status, pending]);
  const original = status?.profiles.find(p => p.id === editing);
  const needsKey = !original?.key_configured || original.provider !== form?.provider;
  const current = status?.profiles.find(p => p.id === status.current_id);
  const disabled = pending || status?.operation?.state === "running";
  function confirmVerification() { return window.confirm("将向所选服务商发送一张内置的 8×8 测试图（不是商品图片），验证真实图片输入与响应，可能产生少量费用。只提交一次，失败不自动重试。继续吗？"); }
  async function mutate(path: string, method: string, extra: object, message: string, closeForm = false) {
    if (busy.current || !status) return;
    busy.current = true; setPending(true); setError(""); setNotice("");
    try {
      const value = await request<VisionStatus>(path, { method, body: JSON.stringify({ expected_revision: status.revision, request_key: crypto.randomUUID(), ...extra }) });
      if (mounted.current) { setStatus(value); setNotice(message); if (closeForm) { setEditing(null); setForm(undefined); } }
    } catch (err) {
      if (mounted.current) setError(err instanceof ApiError ? err.message : "操作结果未确认，请刷新状态后核对；不会自动重试。");
      try { await load(); } catch { if (mounted.current) setError("操作结果未确认，且状态读取失败。请重新读取，勿重复提交。"); }
    } finally { clearKey(); busy.current = false; if (mounted.current) setPending(false); }
  }
  async function save(e: FormEvent) {
    e.preventDefault(); if (!form || !status || busy.current) return;
    const key = keyInput.current?.value ?? "";
    if (needsKey && !key) { setError("请填写该配置的 API Key。"); return; }
    const verifying = !!(original?.current && status.enabled && (JSON.stringify(fields(original)) !== JSON.stringify(form) || key));
    if (verifying && !confirmVerification()) return;
    clearKey();
    await mutate(editing === "new" ? "/api/vision/profiles" : `/api/vision/profiles/${editing}`, editing === "new" ? "POST" : "PATCH",
      { config: form, ...(key ? { key } : {}), verification_confirmed: verifying }, verifying ? "配置已验证并更新，视觉研究保持启用。" : "配置已保存。保存不会验证连接或开启视觉研究。", true);
  }
  function action(p: VisionProfile, kind: "verify" | "select") {
    const verifying = kind === "verify" || !!status?.enabled;
    if (verifying && !confirmVerification()) return;
    void mutate(`/api/vision/profiles/${p.id}/${kind}`, "POST", { verification_confirmed: verifying }, kind === "verify" ? "连接验证通过。视觉研究开关未自动开启。" : "当前模型已切换。");
  }
  function toggle() {
    if (!status || (!status.enabled && !confirmVerification())) return;
    void mutate("/api/vision/feature", "PUT", { enabled: !status.enabled, verification_confirmed: !status.enabled }, status.enabled ? "视觉研究已关闭，配置仍保留。" : "当前模型验证通过，视觉研究已启用。商品图片分析仍需原有审批。");
  }
  return <section className="ss-card vision-settings" aria-label="视觉模型配置">
    <header className="vision-header"><div className="vision-heading"><Eye size={22}/><div><h2>视觉模型</h2><p>管理用于商品图片分析的 AI 服务</p></div></div><button className="sp-primary" disabled={disabled || !status || editing !== null} onClick={() => open()}><Plus size={15}/>添加配置</button></header>
    {error ? <p className="vision-error" role="alert">{error}<button disabled={pending} onClick={() => { setError(""); void load().catch(() => setError("无法读取配置，请稍后重试。")); }}>刷新状态</button></p> : null}
    {notice ? <p className="vision-notice" role="status">{notice}</p> : null}
    {!status ? <p role="status">{error ? "读取失败" : "正在读取本地配置…"}</p> : <>
      <div className="vision-feature"><div><strong>视觉研究</strong><p>{status.enabled ? "已启用" : "已关闭"} · {current ? `当前模型：${providerName(current.provider)} / ${current.model}` : "尚未选择当前模型"}</p></div><button role="switch" aria-checked={status.enabled} aria-label="启用视觉研究" className={`vision-switch${status.enabled ? " is-on" : ""}`} disabled={disabled || editing !== null || (!current && !status.enabled)} onClick={toggle}><span/></button></div>
      <p className="vision-footnote">开启时验证当前模型。商品分析仍需审批，不会自动发送图片。</p>
      {status.legacy_requires_verification ? <p className="vision-help">原配置与密钥已保留；首次启用需重新验证连接。</p> : null}
      {status.operation?.state === "interrupted" ? <p className="vision-error">上次操作被中断，未自动重试。请核对配置后再操作。</p> : null}
      <div className="vision-profile-grid">{status.profiles.map(p => <article className={`vision-profile${p.current ? " is-current" : ""}`} key={p.id} aria-label={`${providerName(p.provider)} ${p.model} 配置`}>
        <div className="vision-profile-heading"><Eye size={20}/><div><h3>{providerName(p.provider)}</h3><p>{p.model}</p></div>{p.current ? <span className="vision-current"><Check size={12}/>当前模型</span> : null}</div>
        <dl className="vision-summary"><div><dt>API Key</dt><dd><LockKeyhole size={13}/>{p.key_configured ? status.storage === "windows_dpapi" ? "已安全保存" : "仅当前进程保存" : "未配置"}</dd></div><div><dt>连接状态</dt><dd className={`vision-connection is-${p.verification.state}`}>{verificationLabel(p.verification.state)}</dd></div></dl>
        {p.verification.checked_at ? <p className="vision-help">验证于 {new Date(p.verification.checked_at).toLocaleString()} · 仅代表该次结果</p> : null}
        <p className="vision-help">超时 {p.timeout_seconds} 秒 · 输出上限 {p.max_output_tokens} Token</p>
        {p.verification.message ? <p className="vision-error">{p.verification.message}</p> : null}
        {!p.capability_declared ? <p className="vision-error">此模型尚无图片输入适配支持，暂不能启用。</p> : null}
        <div className="sp-actions vision-profile-actions"><button disabled={disabled || editing !== null} onClick={() => open(p)}><Pencil size={13}/>修改配置</button><button disabled={disabled || editing !== null || !p.key_configured || !p.capability_declared} onClick={() => action(p,"verify")}><RefreshCw size={13}/>重新验证</button>
          {!p.current ? <button disabled={disabled || editing !== null} onClick={() => action(p,"select")}>设为当前模型</button> : null}
          <button aria-label={`删除配置 ${p.id}`} title={p.current && status.enabled ? "请先关闭视觉研究或切换当前模型" : "删除配置"} disabled={disabled || editing !== null || (p.current && status.enabled)} onClick={() => { if (window.confirm(p.current ? "删除当前配置后将不再选择任何模型。确定删除吗？" : "确定删除这份配置吗？其他配置不受影响。")) void mutate(`/api/vision/profiles/${p.id}`,"DELETE",{confirmed:true},"配置已删除。"); }}><Trash2 size={13}/></button></div>
      </article>)}</div>
      {!status.profiles.length && !editing ? <div className="vision-empty"><p>还没有视觉模型配置</p><button onClick={() => open()}>添加第一个配置</button></div> : null}
      {editing && form ? <form ref={editor} className="vision-editor" onSubmit={e => void save(e)} autoComplete="off" onInvalid={e => { if (e.target instanceof HTMLElement) { const d = e.target.closest("details"); if(d) d.open=true; } }}>
        <h3>{editing === "new" ? "添加配置" : "修改配置"}</h3><fieldset disabled={disabled}><section className="vision-step"><h3><span>1</span>选择服务商和模型</h3><div className="vision-fields">
          <label>服务商<select value={form.provider} onChange={e => { clearKey(); setForm({...form, provider:e.target.value, model:status.providers.find(p=>p.id===e.target.value)?.models[0] ?? ""}); }}>{status.providers.map(p => <option key={p.id} value={p.id}>{providerName(p.id)}</option>)}</select></label><label>模型 ID<input required maxLength={120} pattern="[A-Za-z0-9._:\-]+" value={form.model} onChange={e => setForm({...form,model:e.target.value})}/></label></div><p className="vision-help">可用的图片模型：{status.providers.find(p=>p.id===form.provider)?.models.join("、")}。其他模型需先有服务端适配。</p></section>
          <section className="vision-step"><h3><span>2</span>填写 API Key</h3><label>{needsKey ? "API Key" : "API Key（留空保留现有密钥）"}<input ref={keyInput} type="password" required={needsKey} maxLength={4096} autoComplete="off" spellCheck={false} placeholder={needsKey ? "输入你的 API Key" : "已保存，无需重复填写"}/></label><p className="vision-help">{status.storage === "windows_dpapi" ? "在本机加密保存，不再显示完整内容。" : "仅保存在当前进程，重启后需重新填写。"}</p></section>
          <details className="vision-advanced"><summary>高级设置</summary><div className="vision-fields"><label>请求超时（秒）<input type="number" required min={1} max={300} value={form.timeout_seconds} onChange={e=>setForm({...form,timeout_seconds:Number(e.target.value)})}/></label><label>输出 Token 上限<input type="number" required min={128} max={4000} value={form.max_output_tokens} onChange={e=>setForm({...form,max_output_tokens:Number(e.target.value)})}/></label></div></details></fieldset>
        <div className="vision-save-actions"><button className="sp-primary" type="submit" disabled={disabled}><Save size={15}/>{pending ? "处理中…" : "保存配置"}</button><button type="button" disabled={disabled} onClick={()=>{clearKey();setEditing(null);setForm(undefined);setError("");}}>取消</button></div>{original?.current && status.enabled ? <p className="vision-footnote">修改当前启用的配置会先验证，失败时保留原配置。</p> : null}
      </form> : null}{pending ? <p role="status">正在处理，请勿重复提交…</p> : null}
    </>}
  </section>;
}
