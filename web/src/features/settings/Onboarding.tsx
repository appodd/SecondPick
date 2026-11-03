import { useEffect, useRef } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Database, ShieldCheck, Sparkles, X, Zap } from "lucide-react";
import { CodexPanel, DiagnosticsPanel, SystemErrors, XianyuPanel } from "./SystemPanels";
import { readProgress, saveProgress, setupMode, useSystemState, type SetupMode } from "./systemState";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { onboardingHref, onboardingReturn } from "./onboardingNavigation";
import { rememberedWorkspace } from "../projects/workspaceLocation";
import "../projects/projects.css";
import "./system-settings.css";
import { OnboardingReadiness, preparationsReady } from "./OnboardingReadiness";

const progressKey = "secondpick-onboarding-step-v1";
const modeKey = "secondpick-onboarding-capability-v1";
const pauseKey = "secondpick-onboarding-paused-v1";
const steps = ["基础与采集环境", "闲鱼连接", "AI 驱动", "就绪检查"];

export function FirstRunEntry({ suppress = false }: { suppress?: boolean }) {
  const system = useSystemState();
  const navigate = useNavigate();
  const location = useLocation();
  const projects = useQuery({ queryKey: ["projects", "list"], queryFn: () => api.getTasks(100) });
  useEffect(() => {
    if (!suppress && system.settings.data && !system.settings.isError && !system.settings.data.setup_completed && !readProgress(pauseKey) && projects.data?.items.length === 0 && !location.search.includes("create=1")) {
      const target = onboardingHref("initial", `${location.pathname}${location.search}`);
      navigate(preparationsReady(system) ? `${target}&step=3` : target, { replace: true });
    }
  }, [system.settings.data, system.settings.isError, navigate, location.pathname, location.search, projects.data, suppress]);
  return !system.settings.data?.setup_completed ? <Link className="ss-resume" to={onboardingHref("resume", `${location.pathname}${location.search}`)}>首次配置{readProgress(pauseKey) ? "尚未完成，继续向导 →" : "向导 →"}</Link> : null;
}

export function Onboarding() {
  useEffect(() => { const previous = document.title; document.title = "SecondPick · 使用引导"; return () => { document.title = previous; }; }, []);
  const system = useSystemState();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const review = params.get("mode") === "review";
  const back = onboardingReturn(params.get("returnTo") ?? rememberedWorkspace());
  const projects = useQuery({ queryKey: ["projects", "list"], queryFn: () => api.getTasks(100) });
  const completing = useRef(false);
  const value = params.get("step") ?? (review ? null : readProgress(progressKey));
  const requestedMode = params.get("capability");
  const mode = setupMode(requestedMode ?? (value === "2" ? "ai" : review ? system.settings.data?.setup_mode : readProgress(modeKey) ?? system.settings.data?.setup_mode));
  const rawStep = value !== null && /^[0-4]$/.test(value) ? Math.min(3, Number(value)) : 0;
  const current = mode === "basic" && rawStep === 2 ? 3 : rawStep;
  const visibleSteps = mode === "basic" ? [0, 1, 3] : [0, 1, 2, 3];
  const ready = preparationsReady(system, mode);
  const locked = system.action.isPending || completing.current;
  const completeLabel = mode === "basic" ? "完成基础配置并开始使用" : "完成 AI 增强配置并开始使用";

  // Keep both mode and progress in the URL; a refresh must not change the completion requirements.
  useEffect(() => {
    const recordMode = !!system.settings.data || requestedMode === "basic" || requestedMode === "ai";
    if (params.get("step") === String(current) && params.get("returnTo") === back && (!recordMode || params.get("capability") === mode)) return;
    const next = new URLSearchParams(params);
    next.set("step", String(current)); next.set("returnTo", back);
    if (recordMode) next.set("capability", mode);
    setParams(next, { replace: true });
  }, [current, back, mode, params, setParams, system.settings.data, requestedMode]);
  useEffect(() => {
    if (!review) {
      saveProgress(progressKey, String(current));
      if (system.settings.data || requestedMode === "basic" || requestedMode === "ai") saveProgress(modeKey, mode);
    }
  }, [current, review, mode, system.settings.data, requestedMode]);

  function changeMode(nextMode: SetupMode) {
    if (system.action.isPending || completing.current) return;
    const next = new URLSearchParams(params); next.set("capability", nextMode);
    if (nextMode === "basic" && current === 2) next.set("step", "3");
    setParams(next);
  }
  function setStep(step: number) {
    if (system.action.isPending || completing.current) return;
    const next = new URLSearchParams(params); next.set("step", String(step));
    if (step === 2) next.set("capability", "ai");
    setParams(next);
  }
  function close() {
    if (locked || completing.current) return;
    if (!ready && !window.confirm(mode === "basic"
      ? "基础采集配置尚未就绪，暂时退出后仍可浏览已有数据，新的监控采集需要完成环境检查与闲鱼验证。确定退出吗？"
      : "AI 增强配置尚未全部就绪。采集需要基础环境与闲鱼连接，AI 研究还需要 CLI 与授权。已有数据仍可查看。确定暂时退出吗？")) return;
    if (!system.settings.data?.setup_completed) saveProgress(pauseKey, "true");
    navigate(back, { replace: true });
  }
  function next(skip = false) {
    if (locked || completing.current) return;
    if (skip && !ready && !window.confirm("可以继续查看向导，未就绪的配置不会被标记为完成。确定继续吗？")) return;
    let nextStep = current + 1;
    if (!review && nextStep === 1 && system.states.xianyu.tone === "good") nextStep++;
    if (nextStep === 2 && (mode === "basic" || !review && system.states.codex.tone === "good")) nextStep++;
    setStep(Math.min(3, nextStep));
  }
  async function complete() {
    if (!ready || locked || completing.current || !system.settings.data || system.settings.isError || !review && !projects.isSuccess) return;
    completing.current = true;
    try {
      await system.action.mutateAsync({ kind: "complete", setupMode: mode });
      navigate(!review && !projects.data?.items.length ? "/?create=1" : back, { replace: true });
    } catch { /* Stay on readiness until saving succeeds. */ }
    finally { completing.current = false; }
  }

  return <main className="ss-onboarding"><div className="ss-wizard">
    <aside className="ss-wizard-side">
      <Link className="sp-brand" to={back} onClick={event => { event.preventDefault(); close(); }}><span><Sparkles size={22} /></span>SecondPick</Link>
      <h1>SecondPick 使用引导</h1><p>先检查运行环境，再创建你的选购项目。</p>
      <nav aria-label="使用引导步骤">{visibleSteps.map((step, index) => <button disabled={locked} className={current === step ? "active" : ""} aria-current={current === step ? "step" : undefined} key={step} onClick={() => setStep(step)}><span>{index + 1}</span>{steps[step]}</button>)}</nav>
    </aside>
    <section className="ss-wizard-main">
      <div className="ss-wizard-top"><span>{review ? "已有配置会保留" : "可随时返回继续"}</span><button disabled={locked} onClick={close}><X size={15} />暂时关闭</button></div>
      <p className="sp-eyebrow">STEP 0{visibleSteps.indexOf(current) + 1} / {steps[current]}</p>
      <h2 className="ss-wizard-title">{["准备基础与采集环境", "连接闲鱼账户", "检查 AI 研究驱动", "确认当前可用能力"][current]}</h2>
      <p>{mode === "basic" ? "基础模式用于监控采集与商品管理。应用基础、采集环境和闲鱼连接就绪即可完成，无需 Codex CLI。" : "AI 增强模式在基础采集能力上检查 Codex CLI 与账号授权。自动研究仍需在每个项目中单独确认。"}视觉模型始终可选。</p>
      <fieldset className="ss-setup-modes" disabled={locked}>
        <legend>选择使用模式</legend>
        <div className="ss-setup-mode-grid">{([
          ["basic", "基础模式", "监控采集、浏览和筛选商品，无需配置 AI。"],
          ["ai", "AI 增强模式", "配置 CLI 与授权，按需研究证据和比较候选。"],
        ] as const).map(([key, title, detail]) => <label key={key} className={mode === key ? "is-selected" : ""}><input type="radio" name="setup-mode" aria-label={title} checked={mode === key} onChange={() => changeMode(key)} /><span><strong>{title}</strong><small>{detail}</small></span></label>)}</div>
      </fieldset>
      <SystemErrors system={system} />
      {current === 0 ? <><div className="ss-illustration ss-flow"><Database size={31} /><ArrowRight /><ShieldCheck size={31} /><ArrowRight /><Zap size={31} /></div><DiagnosticsPanel system={system} /></> : null}
      {current === 1 ? <XianyuPanel system={system} /> : null}
      {current === 2 ? <><CodexPanel system={system} /><p className="ss-research-authorization">CLI 账号授权用于连接 AI 服务。创建项目时还需单独确认是否授权自动研究；默认不授权。完成本引导不会调用模型或启动研究。</p></> : null}
      {current === 3 ? <><OnboardingReadiness system={system} mode={mode} prepareStep={setStep} />{!ready ? <p className="ss-readiness-summary" role="status">{mode === "basic" ? "请完成应用基础检查、采集环境和闲鱼连接的配置与验证。AI 和视觉模型不阻止基础模式完成。" : "请完成基础采集配置，以及 Codex CLI 和账号授权检查。视觉模型可跳过。"}</p> : null}</> : null}
      {current === 3 && !review && projects.isError ? <div className="ss-notice" role="alert">无法确认已有项目，请重新读取后完成配置。<button onClick={() => void projects.refetch()}>重新读取</button></div> : null}
      <footer className="ss-wizard-footer"><div>
        {current > 0 ? <button disabled={locked} onClick={() => setStep(visibleSteps[Math.max(0, visibleSteps.indexOf(current) - 1)])}>上一步</button> : null}
        {current < 3 ? <><button disabled={locked} onClick={() => next(true)}>暂不配置</button><button disabled={locked} className="sp-primary" onClick={() => next()}>继续 <ArrowRight size={15} /></button></> : null}
        {current === 3 ? <><button disabled={locked} onClick={close}>暂时退出</button><button className="sp-primary" disabled={!ready || locked || !system.settings.data || system.settings.isError || !review && !projects.isSuccess} onClick={complete}>{system.action.isPending ? "正在保存…" : completeLabel}<ArrowRight size={15} /></button></> : null}
      </div></footer>
    </section>
  </div></main>;
}
