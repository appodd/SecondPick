import { workspaceReturn } from "./contextNavigation";

const key = "secondpick-workspace-location-v1";
/** Presentation context only. Never restore a create/run command from storage. */
export function rememberedWorkspace() {
  try { return workspaceReturn(sessionStorage.getItem(key)).href; } catch { return "/"; }
}
export function rememberWorkspace(source: string) {
  const safe = workspaceReturn(source).href;
  if (safe === "/") return;
  try { sessionStorage.setItem(key, safe); } catch { /* Explicit returnTo still works. */ }
}
