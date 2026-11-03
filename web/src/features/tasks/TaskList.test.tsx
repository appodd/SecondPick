import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskList } from "./TaskList";

afterEach(cleanup);

describe("TaskList", () => {
  it("uses API status and exposes truncated history loading", async () => {
    const onLoadMore = vi.fn();
    render(
      <MemoryRouter>
        <TaskList
          tasks={[
            {
              id: 8,
              title: "Blocked task",
              city: "上海",
              status: "blocked",
              run_count: 3,
              report_count: 2,
              updated_at: "2026-09-16T00:00:00+00:00",
            },
          ]}
          totalCount={125}
          returnedCount={50}
          truncated
          onLoadMore={onLoadMore}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: /Blocked task/ })).toHaveTextContent("已阻断");
    expect(screen.queryByText("已保存")).not.toBeInTheDocument();
    expect(screen.getByText("显示 50 / 125 个任务")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "加载更多任务" }));
    expect(onLoadMore).toHaveBeenCalledOnce();
  });
});
