import { useState } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SetupStatus, UserSettings } from "../../api/types";
import { ConnectionSettings } from "./ConnectionSettings";
import { SetupWizard } from "./SetupWizard";

const incompleteStatus: SetupStatus = {
  setup_completed: false,
  environment: [
    { name: "config", ok: true, detail: "default_city=上海" },
    { name: "database", ok: true, detail: "data/shopping.sqlite" },
  ],
  codex: {
    cli_available: true,
    auth_available: true,
    process_running: false,
    detail: "authenticated",
  },
  xianyu: {
    profile_present: true,
    auth_status: "unknown",
    detail: "profile present; authentication unknown",
  },
  can_browse_existing_data: true,
  can_start_research: false,
};

const settings: UserSettings = {
  setup_completed: false,
  default_city: "上海",
  platforms: ["xianyu"],
  allow_ocr: true,
  preferred_view: "research",
};

function ModalHarness() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>打开设置</button>
      <main data-testid="background-content">后台内容</main>
      {open ? (
        <SetupWizard
          status={incompleteStatus}
          settings={settings}
          onClose={() => setOpen(false)}
          onSaveSettings={vi.fn()}
        />
      ) : null}
    </>
  );
}

afterEach(cleanup);

describe("SetupWizard", () => {
  it("allows history browsing while setup is incomplete", async () => {
    const onClose = vi.fn();

    render(
      <SetupWizard
        status={incompleteStatus}
        settings={settings}
        onClose={onClose}
        onSaveSettings={vi.fn()}
      />,
    );

    expect(screen.getByText("你仍可浏览已有研究数据")).toBeInTheDocument();
    const later = screen.getByRole("button", { name: "稍后完成" });
    expect(later).toBeEnabled();

    await userEvent.click(later);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("saves only supported preferences when the four steps finish", async () => {
    const onSaveSettings = vi.fn().mockResolvedValue(undefined);

    render(
      <SetupWizard
        status={incompleteStatus}
        settings={settings}
        onClose={vi.fn()}
        onSaveSettings={onSaveSettings}
      />,
    );

    expect(screen.getByRole("heading", { name: "环境检查" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("heading", { name: "Codex 可用性" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("heading", { name: "闲鱼登录" })).toBeInTheDocument();
    expect(screen.getByText(/完成引导后，在设置页面/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));

    expect(screen.getByRole("heading", { name: "使用偏好" })).toBeInTheDocument();
    await userEvent.clear(screen.getByRole("textbox", { name: "默认城市" }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "默认城市" }),
      "杭州",
    );
    await userEvent.click(screen.getByRole("button", { name: "完成设置" }));

    expect(onSaveSettings).toHaveBeenCalledWith({
      setup_completed: true,
      default_city: "杭州",
      platforms: ["xianyu"],
      allow_ocr: true,
    });
    expect(screen.getByText("可以开始对话研究；采集前请到设置中登录并验证闲鱼。"))
      .toBeInTheDocument();
  });

  it("does not describe Codex as continuously running", () => {
    render(<ConnectionSettings setup={incompleteStatus} sections={["environment", "codex"]} />);

    expect(screen.getByText("研究请求发生时按需启动")).toBeInTheDocument();
    expect(screen.getByText("按需启动，当前未运行")).toBeInTheDocument();
    expect(screen.queryByText("Codex 已开启")).not.toBeInTheDocument();
  });

  it("traps focus, isolates the background, and restores focus on Escape", async () => {
    const user = userEvent.setup();
    render(<ModalHarness />);

    const trigger = screen.getByRole("button", { name: "打开设置" });
    await user.click(trigger);

    const close = screen.getByRole("button", { name: "关闭引导" });
    const background = screen.getByTestId("background-content");
    expect(close).toHaveFocus();
    expect(document.body).toHaveStyle({ overflow: "hidden" });
    expect(background).toHaveAttribute("aria-hidden", "true");
    expect(background).toHaveProperty("inert", true);

    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "下一步" })).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(close).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "准备本地研究工作台" }))
      .not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(document.body).not.toHaveStyle({ overflow: "hidden" });
    expect(background).not.toHaveAttribute("aria-hidden");
    expect(background).toHaveProperty("inert", false);
  });
});
