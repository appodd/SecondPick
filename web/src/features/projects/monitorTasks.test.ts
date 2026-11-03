import { describe, expect, it } from "vitest";
import type { Monitor } from "../../api/monitorClient";
import type { WindowMonitor } from "../../api/projectClient";
import { canToggleMonitor, monitorCycle, monitorMode, monitorStartAction, monitorTasks, startLabel } from "./monitorTasks";
import { monitorTaskExecution } from "../../components/status/statusModel";

const monitor = { id: 1, task_id: 1, keyword: "笔记本", state: "paused", desired_state: null, rounds: 1, max_rounds: 1000, interval_seconds: 1800 } as Monitor;
const window = { monitor_id: 1, name: "工作区计划", mode: "ongoing", duration_seconds: null, monitor,
  runs: [{ id: 1, state: "paused" }] } as WindowMonitor;
describe("monitor task presentation and existing control scopes", () => {
  it("only offers a switch for known ongoing/timed scopes with an active or paused window", () => {
    const task = monitorTasks([window], [], true)[0];
    expect(canToggleMonitor(task)).toBe(true);
    expect(canToggleMonitor({ ...task, window: { ...window, mode: "once" } })).toBe(false);
    expect(canToggleMonitor({ ...task, window: { ...window, runs: [] } })).toBe(false);
    expect(canToggleMonitor({ ...task, window: undefined })).toBe(false);
  });
  it("distinguishes a stopped automatic schedule from an ended once range without claiming success", () => {
    const task = monitorTasks([{ ...window, monitor: { ...monitor, state: "stopped", error_code: null } }], [], true)[0];
    expect(monitorTaskExecution(task).label).toBe("调度已停止");
    expect(monitorTaskExecution({ ...task, window: { ...window, mode: "once" } }).label).toBe("本次范围已结束");
    expect(monitorTaskExecution(task).kind).toBe("inactive");
    expect(monitorTaskExecution({ ...task, monitor: { ...task.monitor!, error_code: "verification_required" } }).kind).toBe("attention");
  });
  it("merges workspace and native tasks without duplicates or invented execution windows", () => {
    const items = monitorTasks([window], [monitor, { ...monitor, id: 2 }], true);
    expect(items.map(item => item.id)).toEqual([2, 1]);
    expect(items[0].window).toBeUndefined(); expect(items[1].window).toBe(window);
    expect(monitorTasks([], [monitor], false)).toEqual([]);
  });
  it("does not equate a once-only configuration with a repeated thirty-minute schedule", () => {
    const task = monitorTasks([{ ...window, mode: "once" }], [], true)[0];
    expect(monitorMode(task)).toBe("单次采集"); expect(monitorCycle(task)).toBe("采集一轮后结束");
  });
  it("uses native resume for paused live windows and explicit rerun for ended windows", () => {
    const task = monitorTasks([window], [], true)[0];
    expect(monitorStartAction(task)).toBe("resume");
    expect(monitorStartAction({ ...task, window: { ...window, runs: [{ ...window.runs[0], state: "completed" }] } })).toBe("rerun");
    expect(startLabel({ ...task, window: { ...window, runs: [] } })).toBe("重新启动监控");
  });
  it("preserves native bounds and does not invent project-level reruns for old scopes", () => {
    const task = monitorTasks([], [{ ...monitor, state: "stopped", max_rounds: 24 }], true)[0];
    expect(monitorStartAction(task)).toBe("resume"); expect(startLabel(task)).toBe("继续采集");
  });
  it("offers no start action while an exit request or real collection is still active", () => {
    const task = monitorTasks([window], [], true)[0];
    expect(monitorStartAction({ ...task, monitor: { ...monitor, state: "running" } })).toBeNull();
    expect(monitorStartAction({ ...task, monitor: { ...monitor, desired_state: "paused" } })).toBeNull();
    expect(monitorStartAction({ ...task, monitor: undefined })).toBeNull();
  });
});
