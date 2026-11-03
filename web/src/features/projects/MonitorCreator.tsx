import { useEffect, useRef, useState } from "react";
import {
  projectApi,
  type WindowDraft,
  type WindowMonitor,
} from "../../api/projectClient";
import { Modal, Panel } from "./projectUi";
import { AiTaskFeedback, type AiFeedbackState } from "../../components/status/AiTaskFeedback";

export function MonitorCreator({
  id,
  goal,
  close,
  saved,
  existing,
  initialKeyword,
}: {
  id: number;
  goal: string;
  close: () => void;
  saved: () => Promise<void>;
  existing?: WindowMonitor;
  initialKeyword?: string;
}) {
  const [requestKey] = useState(() => crypto.randomUUID());
  const [draft, commitDraft] = useState<WindowDraft>(
    existing
      ? {
          name: existing.name,
          keyword: existing.monitor.keyword,
          mode: existing.mode,
          duration_seconds: existing.duration_seconds ?? 1800,
          interval_seconds: existing.monitor.interval_seconds,
          max_pages: existing.monitor.max_pages,
          max_items: existing.monitor.max_items,
          collect_seller_profiles: existing.monitor.collect_seller_profiles,
        }
      : {
          name: initialKeyword ? `${initialKeyword} · 补充监控` : "",
          keyword: initialKeyword ?? "",
          mode: "timed",
          duration_seconds: 1800,
          interval_seconds: 1800,
          max_pages: 3,
          max_items: 50,
          collect_seller_profiles: false,
        },
  );
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [natural, setNatural] = useState(goal);
  const [parseFeedback, setParseFeedback] = useState<{ state: AiFeedbackState; title: string; description: string }>();
  const edits = useRef(0), parsing = useRef(false), saving = useRef(false), mounted = useRef(true);
  const nameInput = useRef<HTMLInputElement>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  function setDraft(value: WindowDraft) { edits.current++; commitDraft(value); }
  async function parse() {
    if (parsing.current || busy || !natural.trim()) return;
    parsing.current = true;
    const revision = edits.current;
    setBusy(true);
    setError("");
    setParseFeedback({ state: "working", title: "AI 正在整理监控草案…", description: "正在将要求整理为可编辑规则，尚未保存或启动采集。" });
    try {
      const result = await projectApi.monitorDraft(id, natural);
      if (!mounted.current) return;
      if (edits.current !== revision) {
        setParseFeedback({ state: "notice", title: "已保留你的最新编辑", description: "生成期间表单已有修改，本次草案未自动填入。可继续手动编辑或重新生成。" });
        return;
      }
      commitDraft(result);
      setReview(false);
      setParseFeedback({ state: "success", title: "监控草案已整理", description: "请检查下方规则，预览并明确确认后才会保存。" });
    } catch (e) {
      if (mounted.current) setParseFeedback({ state: "error", title: "监控草案未生成", description: `${(e as Error).message}。可重试或继续手动填写。` });
    } finally {
      parsing.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function save() {
    if (saving.current || busy) return;
    saving.current = true;
    setBusy(true);
    setError("");
    try {
      if (existing) {
        await projectApi.editMonitor(id, existing, draft);
      } else {
        await projectApi.createMonitor(id, draft, requestKey);
      }
      await saved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return (
    <Modal title="监控计划草案" close={close}>
      <p>
        项目目标：{goal}
        。生成草案会调用 AI；确认启动后才访问闲鱼。
      </p>
      <label>
        自然语言监控要求
        <textarea
          value={natural}
          onChange={(e) => { edits.current++; setNatural(e.target.value); }}
        />
      </label>
      <button disabled={busy || !natural.trim()} onClick={parse}>
        AI 生成可编辑草案
      </button>
      {parseFeedback ? <AiTaskFeedback {...parseFeedback}>{parseFeedback.state === "error" ? <div className="sp-actions"><button disabled={busy || !natural.trim()} onClick={parse}>重试生成</button><button onClick={() => nameInput.current?.focus()}>手动填写监控规则</button></div> : null}</AiTaskFeedback> : null}
      <label>
        监控名称
        <input
          ref={nameInput}
          value={draft.name}
          onChange={(e) => {
            setReview(false);
            setDraft({ ...draft, name: e.target.value });
          }}
        />
      </label>
      <label>
        搜索关键词
        <input
          value={draft.keyword}
          onChange={(e) => {
            setReview(false);
            setDraft({ ...draft, keyword: e.target.value });
          }}
        />
      </label>
      <label>
        运行方式
        <select
          value={draft.mode}
          onChange={(e) => {
            setReview(false);
            setDraft({ ...draft, mode: e.target.value as WindowDraft["mode"] });
          }}
        >
          <option value="once">单次采集</option>
          <option value="timed">限时监控</option>
          <option value="ongoing">长期周期监控</option>
        </select>
      </label>
      {draft.mode === "timed" ? (
        <label>
          运行窗口（分钟）
          <input
            type="number"
            min="1"
            max="1440"
            value={draft.duration_seconds / 60}
            onChange={(e) => {
              setReview(false);
              setDraft({
                ...draft,
                duration_seconds: Number(e.target.value) * 60,
              });
            }}
          />
        </label>
      ) : null}
      {draft.mode !== "once" ? (
        <label>
          检查间隔（分钟）
          <input
            type="number"
            min="1"
            max="1440"
            value={draft.interval_seconds / 60}
            onChange={(e) => {
              setReview(false);
              setDraft({
                ...draft,
                interval_seconds: Number(e.target.value) * 60,
              });
            }}
          />
        </label>
      ) : null}
      <label>
        每轮搜索页数上限
        <input
          type="number"
          min="1"
          max="50"
          value={draft.max_pages}
          onChange={(e) => {
            setReview(false);
            setDraft({ ...draft, max_pages: Number(e.target.value) });
          }}
        />
      </label>
      <label>
        每轮详情处理上限
        <input
          type="number"
          min="1"
          max="1000"
          value={draft.max_items}
          onChange={(e) => {
            setReview(false);
            setDraft({ ...draft, max_items: Number(e.target.value) });
          }}
        />
      </label>
      <label className="sp-check">
        <input
          type="checkbox"
          checked={draft.collect_seller_profiles}
          onChange={(e) => {
            setReview(false);
            setDraft({ ...draft, collect_seller_profiles: e.target.checked });
          }}
        />
        允许采集公开卖家主页与发布记录
      </label>
      <p className="sp-muted">
        预算用于研究初筛；当前采集引擎未提供严格价格过滤。偏好不会自动转为搜索过滤。
      </p>
      {review ? (
        <Panel className="sp-notice">
          <h3>待确认 · 尚未执行</h3>
          {existing ? (
            <p>
              Monitor #{existing.monitor_id} · 原关键词：
              {existing.monitor.keyword} → 新关键词：{draft.keyword}；原模式：
              {existing.mode} → 新模式：{draft.mode}
              。请先暂停采集；保存会结束暂停的旧窗口，后续需明确再次运行。搜索词限制可能遗漏标题不完整的商品。
            </p>
          ) : null}
          <p>
            {draft.keyword} ·{" "}
            {draft.mode === "timed"
              ? `${draft.duration_seconds / 60} 分钟运行窗口；到期停止新采集`
              : draft.mode === "once"
                ? "采集一轮后结束"
                : "周期检查，直到暂停或停止"}
          </p>
          <p>
            每轮最多 {draft.max_pages} 页搜索、{draft.max_items} 件详情。{draft.collect_seller_profiles ? "包含公开卖家主页。" : "不访问卖家主页。"}
          </p>
          <p>
            采集受平台验证与服务器速率限制，实际频率可能更低。已有研究独立继续。
          </p>
          <button className="sp-primary" disabled={busy} onClick={save}>
            {busy
              ? "提交中…"
              : existing
                ? "明确确认永久变更"
                : "明确确认并启动监控"}
          </button>
        </Panel>
      ) : (
        <button
          className="sp-primary"
          disabled={!draft.name.trim() || !draft.keyword.trim()}
          onClick={() => {
            const valid = (n: number, min: number, max: number) => Number.isInteger(n) && n >= min && n <= max;
            if (!valid(draft.max_pages, 1, 50) || !valid(draft.max_items, 1, 1000) || !valid(draft.interval_seconds, 60, 86400) || !valid(draft.duration_seconds, 60, 86400)) { setError("请检查采集范围：搜索页数1–50，详情数量1–1000，间隔和窗口1–1440分钟。"); return; }
            setError(""); setReview(true);
          }}
        >
          预览计划
        </button>
      )}
      {error ? (
        <p className="sp-error" role="alert">
          {error}
        </p>
      ) : null}
    </Modal>
  );
}
