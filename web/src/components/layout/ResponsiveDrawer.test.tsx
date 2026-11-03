// @ts-expect-error Vitest provides Node APIs while the app tsconfig excludes Node types.
import { readFileSync } from "node:fs";

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";
import { ResponsiveDrawer } from "./ResponsiveDrawer";

const globalCss: string = readFileSync("src/styles/global.css", "utf8");

function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: width,
  });

  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches:
      query === "(min-width: 1180px)"
        ? width >= 1180
        : query === "(max-width: 767px)"
          ? width < 768
          : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

afterEach(() => {
  cleanup();
  document.body.style.overflow = "";
  vi.restoreAllMocks();
});

describe("ResponsiveDrawer", () => {
  it("closes the mobile evidence drawer with Escape and restores focus", async () => {
    const user = userEvent.setup();
    render(
      <ResponsiveDrawer triggerLabel="查看证据" title="上下文检查器">
        <button type="button">证据操作</button>
      </ResponsiveDrawer>,
    );

    const trigger = screen.getByRole("button", { name: "查看证据" });
    await user.click(trigger);
    expect(document.body).toHaveStyle({ overflow: "hidden" });
    expect(screen.getByRole("dialog", { name: "上下文检查器" })).toHaveAttribute(
      "aria-modal",
      "true",
    );

    await user.keyboard("{Escape}");

    expect(
      screen.queryByRole("dialog", { name: "上下文检查器" }),
    ).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(document.body).not.toHaveStyle({ overflow: "hidden" });
  });

  it("traps focus and closes through the backdrop", async () => {
    const user = userEvent.setup();
    render(
      <ResponsiveDrawer triggerLabel="查看证据" title="上下文检查器">
        <button type="button">第一个操作</button>
        <button type="button">最后一个操作</button>
      </ResponsiveDrawer>,
    );

    const trigger = screen.getByRole("button", { name: "查看证据" });
    await user.click(trigger);
    const close = screen.getByRole("button", { name: "关闭上下文检查器" });
    const lastAction = screen.getByRole("button", { name: "最后一个操作" });

    expect(close).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(lastAction).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(close).toHaveFocus();

    await user.click(screen.getByTestId("drawer-backdrop"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
  it('keeps the draft open when text selection begins inside and ends on the backdrop',async()=>{
    const user=userEvent.setup();render(<ResponsiveDrawer triggerLabel="编辑目标" title="目标"><textarea aria-label="目标描述" defaultValue="已有选购草案"/></ResponsiveDrawer>);
    await user.click(screen.getByRole('button',{name:'编辑目标'}));
    const input=screen.getByRole('textbox'),backdrop=screen.getByTestId('drawer-backdrop');
    await user.pointer([{target:input,keys:'[MouseLeft>]'},{target:backdrop},{target:backdrop,keys:'[/MouseLeft]'}]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();expect(input).toHaveValue('已有选购草案');
    await user.click(backdrop);expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('does not dismiss when an outside drag ends inside the dialog',async()=>{
    const user=userEvent.setup();render(<ResponsiveDrawer triggerLabel="编辑目标" title="目标"><textarea aria-label="目标描述"/></ResponsiveDrawer>);
    await user.click(screen.getByRole('button',{name:'编辑目标'}));
    await user.pointer([{target:screen.getByTestId('drawer-backdrop'),keys:'[MouseLeft>]'},{target:screen.getByRole('textbox')},{target:screen.getByRole('textbox'),keys:'[/MouseLeft]'}]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'关闭目标'}));expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('does not treat a backdrop drag as a click',async()=>{
    const user=userEvent.setup();render(<ResponsiveDrawer triggerLabel="编辑目标" title="目标"><p>目标草案</p></ResponsiveDrawer>);
    await user.click(screen.getByRole('button',{name:'编辑目标'}));const target=screen.getByTestId('drawer-backdrop');
    await user.pointer([{target,coords:{x:10,y:10},keys:'[MouseLeft>]'},{target,coords:{x:80,y:80}},{target,keys:'[/MouseLeft]'}]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});

describe("AppShell responsive integration", () => {
  function renderShell() {
    return render(
      <AppShell
        sidebar={<button type="button">任务一</button>}
        main={<div>工作区</div>}
        context={<button type="button">证据一</button>}
      />,
    );
  }

  it("keeps all three columns persistent at desktop width", () => {
    setViewport(1180);
    renderShell();

    expect(screen.getByRole("navigation", { name: "研究任务" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("工作区");
    expect(
      screen.getByRole("complementary", { name: "上下文检查器" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查看证据" })).not.toBeInTheDocument();
  });

  it("uses a collapsible task rail and context drawer at tablet width", async () => {
    const user = userEvent.setup();
    setViewport(900);
    renderShell();

    expect(screen.getByRole("navigation", { name: "研究任务" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "上下文检查器" }))
      .not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "收起任务导航" }));
    expect(screen.queryByRole("navigation", { name: "研究任务" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开任务导航" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看证据" }));
    expect(screen.getByRole("dialog", { name: "上下文检查器" })).toHaveTextContent(
      "证据一",
    );
  });

  it("moves navigation and context into modal drawers below 768px", async () => {
    const user = userEvent.setup();
    setViewport(767);
    renderShell();

    expect(screen.queryByRole("navigation", { name: "研究任务" })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "上下文检查器" }))
      .not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看任务" }));
    expect(screen.getByRole("dialog", { name: "研究任务" })).toHaveTextContent("任务一");
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "查看证据" }));
    expect(screen.getByRole("dialog", { name: "上下文检查器" })).toHaveTextContent(
      "证据一",
    );
  });

  it("keeps card grids single-column in the final mobile cascade", () => {
    const debugGridColumns = Array.from(
      globalCss.matchAll(
        /\.debug-summary-grid\s*\{[^}]*grid-template-columns:\s*([^;]+);/g,
      ),
      (match) => match[1].trim(),
    );

    expect(debugGridColumns.at(-1)).toBe("minmax(0, 1fr)");
  });
});
