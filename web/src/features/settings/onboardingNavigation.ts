import { workspaceReturn } from "../projects/contextNavigation";

/** Only restore known application views, never commands, external URLs or the wizard itself. */
export function onboardingReturn(value: string | null): string {
  if (!value || value.length > 5000) return "/";
  if (/^\/projects\/[1-9]\d*(?:\?|$)/.test(value)) {
    return workspaceReturn(value.includes("?") ? value : `${value}?view=overview`).href;
  }
  if (!/^\/settings(?:\?|$)/.test(value)) return "/";
  const url = new URL(value, "https://secondpick.local");
  if (url.origin !== "https://secondpick.local" || url.pathname !== "/settings") return "/";
  const params = new URLSearchParams();
  const section = url.searchParams.get("section");
  if (section && ["overview", "xianyu", "codex", "vision", "diagnostics"].includes(section)) params.set("section", section);
  const back = workspaceReturn(url.searchParams.get("returnTo"));
  if (back.href !== "/") params.set("returnTo", back.href);
  return `/settings${params.size ? `?${params}` : ""}`;
}
export function onboardingHref(mode: "initial" | "resume" | "review", source: string) {
  const params = new URLSearchParams({ mode, returnTo: onboardingReturn(source) });
  if (mode === "review") params.set("step", "0");
  return `/onboarding?${params}`;
}
