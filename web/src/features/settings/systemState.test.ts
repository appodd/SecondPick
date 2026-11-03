import { describe, expect, it } from "vitest";
import { preparationsReady, serviceStates, type SystemState } from "./systemState";
import type { SetupStatus } from "../../api/types";
import type { BrowserStatus } from "../../api/browserClient";

const setup: SetupStatus = {
  setup_completed: true, environment: [{ name: "database", ok: true, detail: "local" }],
  codex: { cli_available: true, auth_available: true, process_running: false, detail: "authenticated" },
  xianyu: { profile_present: true, auth_status: "unknown", detail: "profile present" },
  can_browse_existing_data: true, can_start_research: false,
};
const browser: BrowserStatus = { auth_status: "verified", enabled: true, active_job: null, login_job: null, max_pages: 3 };
describe("system readiness truth boundaries", () => {
  it("requires every collection dependency in either mode, and CLI only in AI mode", () => {
    const good = { tone: "good", label: "ready", detail: "" };
    const system = { healthState: good, settings: { data: { setup_mode: "basic" } }, states: {
      environment: good, xianyu: good, collection: good, codex: { ...good, tone: "unknown" },
    } } as unknown as SystemState;
    expect(preparationsReady(system, "basic")).toBe(true);
    expect(preparationsReady(system, "ai")).toBe(false);
    system.states.codex = good as SystemState['states']['codex'];
    expect(preparationsReady(system, "ai")).toBe(true);
    for (const dependency of ['environment', 'xianyu', 'collection'] as const) {
      const previous = system.states[dependency];
      system.states[dependency] = { tone: 'unknown', label: 'stale', detail: '' };
      expect(preparationsReady(system, 'basic')).toBe(false);
      expect(preparationsReady(system, 'ai')).toBe(false);
      system.states[dependency] = previous;
    }
    system.healthState = { tone: 'warn', label: 'offline', detail: '' };
    expect(preparationsReady(system, 'basic')).toBe(false);
  });
  it("does not infer authentication from a local profile or setup completion", () => {
    expect(serviceStates(setup).xianyu.tone).toBe("unknown");
    expect(serviceStates(setup, { ...browser, auth_status: "unknown" }).xianyu.label).toBe("尚未验证");
  });
  it("uses persisted browser authentication independently from the setup summary", () => {
    expect(serviceStates(setup, browser).xianyu.label).toBe("已验证");
    expect(serviceStates(setup, { ...browser, auth_status: "invalid" }).xianyu.tone).toBe("warn");
  });
  it("keeps CLI discovery and authorization failures separate", () => {
    expect(serviceStates({ ...setup, codex: { ...setup.codex, cli_available: false } }).codex.label).toBe("未检测到 CLI");
    expect(serviceStates({ ...setup, codex: { ...setup.codex, auth_available: false } }).codex.label).toBe("授权未通过");
  });
  it("does not count empty environment results or missing engine checks as ready", () => {
    expect(serviceStates({ ...setup, environment: [] }).environment.tone).toBe("unknown");
    expect(serviceStates(setup, browser).collection.tone).toBe("unknown");
    expect(serviceStates(undefined, undefined).codex.tone).toBe("unknown");
  });
  it("does not treat an authorization probe failure as a proven authentication rejection", () => {
    expect(serviceStates({ ...setup, codex: { ...setup.codex, auth_available: false, detail: "check failed" } }).codex.tone).toBe("unknown");
  });
  it("labels local engine checks without claiming the collector is running", () => {
    const result = serviceStates(setup, browser, { ready: true, checked_at: "2026-10-22", checks: [] });
    expect(result.collection.label).toBe("环境检查通过");
    expect(result.collection.detail).toContain("不代表正在采集或已启用");
  });
});
