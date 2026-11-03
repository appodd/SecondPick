import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, request } from "../../api/client";
import { browserApi, isBrowserActive, type BrowserStatus } from "../../api/browserClient";
import { monitorApi, type MonitorReadiness } from "../../api/monitorClient";
import type { SetupStatus } from "../../api/types";
import { useEffect, useState } from "react";
import type { StatusKind } from "../../components/status/statusModel";

export type ServiceState = { label: string; tone: "good" | "warn" | "unknown"; detail: string; kind?: StatusKind };
export type SetupMode = "basic" | "ai";
type SystemAction = "environment" | "codex" | "engine" | "login" | "verify" | "cancel" | "complete" | "refresh"
  | { kind: "complete"; setupMode: SetupMode };
export function setupMode(value: unknown): SetupMode { return value === "ai" ? "ai" : "basic"; }
type ObservedSetup = SetupStatus & { _fieldObserved?: { environment: number; codex: number } };
export function serviceStates(setup?: SetupStatus, browser?: BrowserStatus, engine?: MonitorReadiness | null) {
  const environment: ServiceState = !setup ? { label: "未知", tone: "unknown", detail: "尚未取得本地环境检查结果。" }
    : setup.environment.length === 0 ? { label: "待检查", tone: "unknown", detail: "后端未返回环境检查项。" }
    : setup.environment.every(check => check.ok) ? { label: "检查通过", tone: "good", detail: "配置与数据库检查通过；不代表浏览器或采集服务已就绪。" }
    : { label: "需要处理", tone: "warn", detail: "部分本地环境检查未通过，请查看诊断并修复。" };
  const xianyu: ServiceState = !browser ? { label: "未知", tone: "unknown", detail: "未取得闲鱼连接状态，请重试读取。" }
    : browser.auth_status === "invalid" ? { label: "需要重新登录", tone: "warn", detail: "后端记录登录失效；新采集和补抓可能受限，已有数据仍可查看。" }
    : browser.auth_status === "verified" ? { label: "已验证", tone: "good", detail: "后端保存的最近验证结果；此页面不会自动访问闲鱼验证有效性。" }
    : { label: "尚未验证", tone: "unknown", detail: "已有登录文件不等于授权有效。请打开登录窗口，完成后明确验证。" };
  const codex: ServiceState = !setup ? { label: "未知", tone: "unknown", detail: "未取得 AI 驱动检查结果。" }
    : !setup.codex.cli_available ? { label: "未检测到 CLI", tone: "warn", detail: "后端未找到 Codex CLI，暂不能提交新的 AI 研究。请检查服务进程的运行环境。" }
    : !setup.codex.auth_available && setup.codex.detail === "check failed" ? { label: "检测未完成", tone: "unknown", detail: "CLI 已找到，但授权检查执行失败或超时，无法确认授权状态。请稍后重试检测。" }
    : !setup.codex.auth_available ? { label: "授权未通过", tone: "warn", detail: "CLI 已找到，但授权检测未通过。请在后端所在设备完成现有 CLI 授权后重新检测。" }
    : { label: "CLI 与授权可用", tone: "good", detail: "基础检测通过；不等于已完成真实研究任务测试。" };
  const collection: ServiceState = !engine ? { label: "尚未检查", tone: "unknown", detail: "可手动检查本地采集环境，不访问闲鱼；引擎启用状态仍由项目监控接口决定。" }
    : engine.ready ? { label: "环境检查通过", tone: "good", detail: "仅确认最近一次本地依赖与浏览器探测通过，不代表正在采集或已启用。" }
    : { label: "环境需要处理", tone: "warn", detail: "本地采集环境检查未通过，修复后可重新检测。" };
  return { environment, xianyu, codex, collection };
}

export function useSystemState() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 10000); return () => clearInterval(timer); }, []);
  const cache = useQueryClient();
  const readOptions = { staleTime: 30_000, refetchOnWindowFocus: false, retry: false } as const;
  const setup = useQuery({ queryKey: ["setup-status"], queryFn: api.getSetupStatus, ...readOptions });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.getSettings, ...readOptions });
  const health = useQuery({ queryKey: ["system-health"], queryFn: async () => {
    const data = await request<{ status: string }>("/api/health");
    if (data.status !== "ok") throw new Error("后端未报告正常状态");
    return data;
  }, ...readOptions });
  const browser = useQuery({ queryKey: ["browser-status"], queryFn: browserApi.status, ...readOptions,
    refetchInterval: query => isBrowserActive(query.state.data?.active_job) ? 2000 : false });
  const engine = useQuery({ queryKey: ["system-engine"], queryFn: monitorApi.environment, ...readOptions });
  const action = useMutation({ mutationFn: async (command: SystemAction) => {
    const kind = typeof command === "string" ? command : command.kind;
    if (kind === "environment") {
      const environment = await api.checkEnvironment();
      cache.setQueryData<ObservedSetup>(["setup-status"], previous => previous ? { ...previous, environment,
        _fieldObserved: { environment: Date.now(), codex: previous._fieldObserved?.codex ?? setup.dataUpdatedAt } } : previous);
      if (!setup.data) await setup.refetch({ throwOnError: true });
    } else if (kind === "codex") {
      const codex = await api.checkCodex();
      cache.setQueryData<ObservedSetup>(["setup-status"], previous => previous ? { ...previous, codex,
        _fieldObserved: { codex: Date.now(), environment: previous._fieldObserved?.environment ?? setup.dataUpdatedAt } } : previous);
      if (!setup.data) await setup.refetch({ throwOnError: true });
    } else if (kind === "engine") {
      cache.setQueryData(["system-engine"], { result: await monitorApi.checkEnvironment() });
    } else if (kind === "complete") {
      const mode = typeof command === "string" ? setupMode(settings.data?.setup_mode) : command.setupMode;
      cache.setQueryData(["settings"], await api.updateSettings({ setup_completed: true, setup_mode: mode }));
    } else if (kind === "refresh") {
      await Promise.all([health.refetch({ throwOnError: true }), setup.refetch({ throwOnError: true }),
        settings.refetch({ throwOnError: true }), browser.refetch({ throwOnError: true }), engine.refetch({ throwOnError: true })]);
    } else {
      const job = browser.data?.login_job;
      if (kind !== "login" && !job) throw new Error("没有可操作的登录任务，请重新读取状态。");
      if (kind === "login") await browserApi.login();
      if (kind === "verify") await browserApi.verify(job!.id);
      if (kind === "cancel") await browserApi.cancel(job!.id);
      await cache.invalidateQueries({ queryKey: ["browser-status"] });
    }
  }});
  // A failed refresh must never leave an old green status looking current.
  const states = serviceStates(setup.isError ? undefined : setup.data, browser.isError ? undefined : browser.data,
    engine.isError ? undefined : engine.data?.result);
  const fieldObserved = (setup.data as ObservedSetup | undefined)?._fieldObserved;
  const observedAt = { environment: fieldObserved?.environment ?? setup.dataUpdatedAt, codex: fieldObserved?.codex ?? setup.dataUpdatedAt,
    engine: engine.data?.result ? Date.parse(engine.data.result.checked_at) : engine.dataUpdatedAt };
  function observed(state: ServiceState, at: number, pending: boolean): ServiceState {
    if (pending) return { label: "正在读取或检测", tone: "unknown", kind: "running", detail: "正在等待已有后端状态接口返回结果。" };
    if ((at && now - at > 300_000) || (!Number.isFinite(at) && state.tone === "good")) return { label: "状态暂不可确认", tone: "unknown", detail: `上次结果：${state.label}。检查时间缺失或超过五分钟未更新，请明确重新检查；不自动验证平台。` };
    return state;
  }
  const pending = (kind: string) => action.isPending && action.variables === kind;
  states.environment = observed(states.environment, observedAt.environment, setup.isFetching || pending("environment"));
  states.codex = observed(states.codex, observedAt.codex, setup.isFetching || pending("codex"));
  states.xianyu = observed(states.xianyu, browser.dataUpdatedAt, browser.isLoading);
  states.collection = observed(states.collection, observedAt.engine, engine.isLoading || pending("engine"));
  const healthState = observed({ label: health.isError ? "后端连接失败" : health.data ? "后端已连接" : "状态未知",
    tone: health.isError ? "warn" : health.data ? "good" : "unknown", detail: "仅表示本地 HTTP 服务响应，不代表采集或 AI 正在执行。" }, health.isError ? health.errorUpdatedAt : health.dataUpdatedAt, health.isFetching);
  return { setup, settings, health, healthState, browser, engine, states, action, observe: observed, observedAt };
}
export type SystemState = ReturnType<typeof useSystemState>;
export function collectionPrepared(system:SystemState) {
  return system.healthState.tone==='good' && system.states.environment.tone==='good' && system.states.xianyu.tone==='good' && system.states.collection.tone==='good';
}
export function preparationsReady(system:SystemState, mode:SetupMode=setupMode(system.settings.data?.setup_mode)) {
  return collectionPrepared(system) && (mode==='basic' || system.states.codex.tone==='good');
}

export function readProgress(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
export function saveProgress(key: string, value: string) { try { localStorage.setItem(key, value); } catch { /* UI still works without storage. */ } }
