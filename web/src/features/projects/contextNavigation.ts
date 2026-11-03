import { useLayoutEffect } from "react";
import { useLocation } from "react-router-dom";

const sourceViews: Record<string, string> = { products: "返回商品列表", shortlist: "返回候选清单", overview: "返回研究概览", monitors: "返回监控任务", research: "返回 Agent 研究" };
export function projectReturn(project: number, value: string | null, depth = 0, allowMarket = false): { href: string; label: string } {
  const fallback = { href: `/projects/${project}?view=products&display=table`, label: "返回商品列表" };
  // The workspace center can legitimately link across projects; ordinary project sources cannot.
  if (allowMarket && depth === 0 && value && value.length <= 4000) {
    const match = value.match(/^\/projects\/([1-9]\d*)\?/), origin = Number(match?.[1]);
    if (match && origin !== project && Number.isSafeInteger(origin) && new URL(value, "https://secondpick.local").searchParams.get("runtime") === "1") { const back = projectReturn(origin, value, depth + 1, true); return back.label === "返回运行中心" ? back : fallback; }
  }
  if (depth > 2 || !value || value.length > 4000 || !value.startsWith(`/projects/${project}?`)) return fallback;
  const url = new URL(value, "https://secondpick.local");
  const view = url.searchParams.get("view") ?? "overview";
  if (url.origin !== "https://secondpick.local" || url.pathname !== `/projects/${project}` || !Object.hasOwn(sourceViews, view) || (!allowMarket && view === "products" && url.searchParams.get("display") === "market")) return fallback;
  // Copy only page presentation state, never an unrelated command or drawer parameter.
  const params = new URLSearchParams({ view });
  for (const key of ["display", "q", "state", "sort", "match", "ai", "page", "fields", "compare", ...(allowMarket ? ["marketFor", "market_model", "market_chip", "market_memory", "market_storage", "market_screen", "market_year", "monitor", "logs", "run", "logRound", "runtime"] : [])]) {
    const item = url.searchParams.get(key);
    if (item !== null) params.set(key, item);
  }
  if (url.searchParams.has("returnTo")) params.set("returnTo", projectReturn(project, url.searchParams.get("returnTo"), depth + 1, allowMarket).href);
  return { href: `${url.pathname}?${params}`, label: allowMarket && params.get("runtime") === "1" ? "返回运行中心" : allowMarket && params.get("display") === "market" ? "返回行情分析" : sourceViews[view] };
}
/** Exact safe project view for a detour to settings or the legacy workbench. */
export function entryHref(project: number, target: string, source: string) {
  const next = new URL(target, "https://secondpick.local");
  next.searchParams.set("returnTo", projectReturn(project, source, 0, true).href);
  return `${next.pathname}?${next.searchParams}${next.hash}`;
}
export function workspaceReturn(value: string | null): { href: string; label: string } {
  const match = value?.match(/^\/projects\/([1-9]\d*)\?/), project = Number(match?.[1]);
  return match && Number.isSafeInteger(project) ? projectReturn(project, value, 0, true) : { href: "/", label: "返回工作台" };
}
export function contextHref(project: number, target: string, source: string): string {
  const current = new URL(source, "https://secondpick.local");
  const origin = current.searchParams.get("display") === "market" ? current.searchParams.get("returnTo") : source;
  const back = projectReturn(project, origin);
  const next = new URL(target, "https://secondpick.local");
  next.searchParams.set("returnTo", back.href);
  return `${next.pathname}?${next.searchParams}${next.hash}`;
}
export function useContextHref(project: number) {
  const location = useLocation();
  return (target: string) => contextHref(project, target, `${location.pathname}${location.search || "?view=overview"}`);
}
export function useEntryHref(project: number) {
  const location = useLocation();
  return (target: string) => entryHref(project, target, `${location.pathname}${location.search || "?view=overview"}`);
}

function scrollKey(pathname: string, search: string) {
  const params = new URLSearchParams(search), state = new URLSearchParams();
  for (const key of ["view", "display", "q", "state", "sort", "match", "ai", "page", "fields", "marketFor"]) {
    const value = params.get(key);
    if (value !== null) state.set(key, value);
  }
  return `secondpick:scroll:${pathname}?${state}`;
}
export function useViewScrollRestoration(ready: boolean) {
  const location = useLocation(), key = scrollKey(location.pathname, location.search);
  useLayoutEffect(() => {
    if (!ready) return;
    const previous = history.scrollRestoration;
    history.scrollRestoration = "manual";
    let saved = 0;
    try { saved = Number(sessionStorage.getItem(key)) || 0; } catch { /* Storage may be unavailable. */ }
    const frame = requestAnimationFrame(() => {
      let anchor: HTMLElement | null = null;
      try { anchor = location.hash ? document.getElementById(decodeURIComponent(location.hash.slice(1))) : null; } catch { /* Invalid fragments use the normal scroll fallback. */ }
      if (anchor) anchor.scrollIntoView({ block: "start", behavior: "instant" });
      else window.scrollTo({ top: saved, behavior: "instant" });
    });
    const save = () => { try { sessionStorage.setItem(key, String(window.scrollY)); } catch { /* Navigation still works without storage. */ } };
    window.addEventListener("scroll", save, { passive: true });
    window.addEventListener("pagehide", save);
    // Do not read scrollY after a route's DOM shrinks: the browser may already have clamped it.
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", save); window.removeEventListener("pagehide", save); history.scrollRestoration = previous; };
  }, [key, ready, location.hash]);
}
