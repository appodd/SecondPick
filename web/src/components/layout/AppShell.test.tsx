import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";

afterEach(cleanup);

describe("AppShell", () => {
  it("keeps navigation, workspace, and context as separate landmarks", () => {
    render(
      <AppShell
        sidebar={<div>Tasks</div>}
        main={<div>Workspace</div>}
        context={<div>Evidence</div>}
      />,
    );

    expect(
      screen.getByRole("navigation", { name: "研究任务" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("Workspace");
    expect(
      screen.getByRole("complementary", { name: "上下文检查器" }),
    ).toBeInTheDocument();
  });

  it("preserves the conversation position for evidence changes and resets it for another task", () => {
    const props = { sidebar: <div>Tasks</div>, main: <div>Workspace</div>, context: <div>Evidence</div> };
    const view = render(<AppShell {...props} navigationKey="/tasks/1" />);
    const main = screen.getByRole("main");
    main.scrollTop = 300;
    view.rerender(<AppShell {...props} navigationKey="/tasks/1?listing=8&context=open" />);
    expect(main.scrollTop).toBe(300);
    view.rerender(<AppShell {...props} navigationKey="/tasks/2" />);
    expect(main.scrollTop).toBe(0);
  });
});
