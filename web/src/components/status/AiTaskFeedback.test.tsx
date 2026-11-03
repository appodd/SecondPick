import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AiTaskFeedback } from "./AiTaskFeedback";
afterEach(() => { cleanup(); vi.useRealTimers(); });
it("updates long-wait feedback without inventing phases, percentages or an ETA", () => {
  vi.useFakeTimers();
  const { rerender } = render(<AiTaskFeedback state="working" title="AI 正在解析选购目标…" description="正在等待结果" />);
  expect(screen.getByText("正在等待结果")).toBeVisible();
  act(() => vi.advanceTimersByTime(16000)); expect(screen.getByText(/仍在等待 AI 返回/)).toBeVisible();
  act(() => vi.advanceTimersByTime(30000)); expect(screen.getByText(/本次等待较久/)).toBeVisible();
  expect(screen.queryByRole("progressbar")).toBeNull();
  rerender(<AiTaskFeedback state="success" title="已整理选购条件" />);
  expect(screen.queryByText(/已等待/)).toBeNull();
  expect(screen.getByText("已整理选购条件")).toHaveAttribute("data-kind", "success");
  expect(vi.getTimerCount()).toBe(0);
});
