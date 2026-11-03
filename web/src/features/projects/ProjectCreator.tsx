import { useEffect, useRef, useState } from "react";
import { projectApi, type ProjectDraft } from "../../api/projectClient";
import { Modal, emptyDraft } from "./projectUi";
import { AiTaskFeedback, type AiFeedbackState } from "../../components/status/AiTaskFeedback";

export function ProjectCreator({
  close,
  created,
}: {
  close: () => void;
  created: (id: number, monitor: boolean) => Promise<void>;
}) {
  const [requestKey] = useState(() => crypto.randomUUID());
  const [draft, setDraft] = useState<ProjectDraft>(emptyDraft);
  const [busy, setBusy] = useState(false);
  const [parsing, setParsing] = useState(false);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const current = useRef(draft);
  const revisions = useRef<Record<keyof ProjectDraft, number>>({ title: 0, goal: 0, budget: 0, hard: 0, soft: 0, minimum: 0, auto_research: 0, auto_cover_cache: 0 });
  const titleInput = useRef<HTMLInputElement>(null);
  const [feedback, setFeedback] = useState<{ state: AiFeedbackState; title: string; description: string }>();
  const [error, setError] = useState("");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  function edit<K extends keyof ProjectDraft>(key: K, value: ProjectDraft[K]) {
    revisions.current[key]++;
    current.current = { ...current.current, [key]: value };
    setDraft(current.current);
    if (key === "goal" && feedback && feedback.state !== "working") setFeedback({ state: "notice", title: "选购目标已修改，可重新解析", description: "已有条件已保留，请按最新目标核对或重新解析。" });
  }
  async function parse() {
    if (inFlight.current || busy || !current.current.goal.trim()) return;
    inFlight.current = true;
    setParsing(true);
    const before = { ...revisions.current };
    const goal = current.current.goal;
    setError("");
    setFeedback({ state: "working", title: "AI 正在解析选购目标…", description: "正在整理预算、硬条件和偏好。你可以继续编辑，手动修改会被保留。" });
    try {
      const result = await projectApi.draft(goal);
      if (!mounted.current) return;
      if (revisions.current.goal !== before.goal) {
        setFeedback({ state: "notice", title: "选购目标已修改，请重新解析", description: "本次结果基于之前提交的目标，未填入表单。你的最新输入已保留。" });
        return;
      }
      const next = { ...current.current };
      const protectedFields = [];
      for (const key of ["title", "budget", "hard", "soft"] as const) {
        if (revisions.current[key] === before[key]) Object.assign(next, { [key]: result[key] });
        else protectedFields.push(key);
      }
      current.current = next;
      setDraft(next);
      setFeedback({ state: "success", title: "已整理选购条件", description: protectedFields.length
        ? "已填入未改动的字段，并保留你在等待期间的修改。请核对下方条件，草案尚未保存。"
        : "已识别预算、硬条件与偏好。请核对并编辑下方条件，草案尚未保存。" });
    } catch (e) {
      if (mounted.current) setFeedback({ state: "error", title: "需求解析未完成", description: `${(e as Error).message}。已保留表单，可重试或手动填写。` });
    } finally {
      inFlight.current = false;
      if (mounted.current) setParsing(false);
    }
  }
  async function save(monitor: boolean) {
    if (inFlight.current || busy) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const project = await projectApi.create(draft, requestKey);
      await created(project.id, monitor);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <Modal title="新建选购项目" close={close} bodyTitle={false}>
      <p>围绕一个购买目标，持续收集商品、比较候选并更新选购建议。</p>
      <label>
        选购目标
        <textarea
          value={draft.goal}
          onChange={(e) => edit("goal", e.target.value)}
          placeholder="例如：想买二手 NS2 Pro 手柄，预算 400 元，不能有摇杆漂移，需提供功能测试。"
        />
      </label>
      <button aria-busy={parsing} disabled={busy || parsing || !draft.goal.trim()} onClick={parse}>
        AI 解析需求
      </button>
      {feedback ? <AiTaskFeedback {...feedback}>
        {feedback.state === "success" ? <dl aria-label="已整理的选购条件"><dt>预算上限</dt><dd>{draft.budget === null ? "待填写" : `¥${draft.budget.toLocaleString()}`}</dd><dt>硬条件</dt><dd>{draft.hard.filter(Boolean).join("；") || "待补充"}</dd><dt>软偏好</dt><dd>{draft.soft.filter(Boolean).join("；") || "待补充"}</dd></dl> : null}
        {feedback.state === "error" ? <div className="sp-actions"><button disabled={busy || parsing || !draft.goal.trim()} onClick={parse}>重试解析</button><button onClick={() => titleInput.current?.focus()}>手动填写</button></div> : null}
      </AiTaskFeedback> : null}
      <label>
        项目名称
        <input
          ref={titleInput}
          value={draft.title}
          maxLength={60}
          onChange={(e) => edit("title", e.target.value)}
        />
      </label>
      <label>
        预算上限（元）
        <input
          type="number"
          min="0"
          value={draft.budget ?? ""}
          onChange={(e) =>
            edit("budget", e.target.value === "" ? null : Number(e.target.value))
          }
        />
      </label>
      <label>
        硬条件（每行一项）
        <textarea
          value={draft.hard.join("\n")}
          onChange={(e) =>
            edit("hard", e.target.value.split("\n"))
          }
        />
      </label>
      <label>
        软偏好（每行一项）
        <textarea
          value={draft.soft.join("\n")}
          onChange={(e) =>
            edit("soft", e.target.value.split("\n"))
          }
        />
      </label>
      <label>
        首轮初步样本门槛
        <input
          type="number"
          min="1"
          max="200"
          value={draft.minimum}
          onChange={(e) =>
            edit("minimum", Number(e.target.value))
          }
        />
      </label>
      <label className="sp-check"><input type="checkbox" checked={draft.auto_cover_cache!==false} onChange={e=>edit("auto_cover_cache",e.target.checked)}/>自动缓存新商品封面（默认开启，可关闭；不调用 AI）</label>
      <label className="sp-check">
        <input
          type="checkbox"
          checked={draft.auto_research}
          onChange={(e) =>
            edit("auto_research", e.target.checked)
          }
        />
        授权自动批次研究（调用已配置 AI；最长等待10分钟后可进行有限样本研究）
      </label>
      {error ? (
        <p className="sp-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="sp-actions">
        <button
          disabled={busy || parsing || !draft.title.trim() || !draft.goal.trim()}
          onClick={() => save(false)}
        >
          仅创建项目
        </button>
        <button
          className="sp-primary"
          disabled={busy || parsing || !draft.title.trim() || !draft.goal.trim()}
          onClick={() => save(true)}
        >
          确认需求并配置监控
        </button>
      </div>
    </Modal>
  );
}
