import { expect, test, type Page } from "@playwright/test";

async function send(page: Page, message: string) {
  await page.getByRole("textbox", { name: "对话输入" }).fill(message);
  const submitted = page.waitForResponse(r => r.request().method() === 'POST' && /\/api\/tasks(?:\/\d+\/messages)?$/.test(new URL(r.url()).pathname));
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const response = await submitted;
  if (/history-|legacy-goal|structured-fixture/.test(message)) {
    const {operation} = await response.json();
    await expect.poll(async()=> (await(await page.request.get(`/api/operations/${operation.id}`)).json()).operation.state,
      {timeout:15000}).toMatch(/^(completed|failed)$/);
  }
}
async function newTask(page: Page, message: string) {
  await page.goto("/new");
  await send(page, message);
  await expect(page).toHaveURL(/\/tasks\/\d+/);
}

test("check suggestions require confirmation, deduplicate and reject stale basis", async ({ page }, info) => {
  const taskId = info.project.name === "mobile-chromium" ? 15 : 14;
  await page.goto(`/tasks/${taskId}?tab=candidates`);
  const data = await (await page.request.get(`/api/tasks/${taskId}/candidates?limit=4`)).json();
  const listingId = Math.min(...data.candidates.map((c: { listing_id: number }) => c.listing_id));
  const listing = data.candidates.find((c: { listing_id: number }) => c.listing_id === listingId);
  await page.getByRole("tab", { name: "对话", exact: true }).click();
  const base = `/api/tasks/${taskId}/listings/${listingId}`;
  const close = () => page.getByRole("button", { name: info.project.name === "mobile-chromium" ? "关闭上下文检查器" : "关闭商品证据", exact: true }).click();
  const open = async () => {
    await page.getByRole("button", { name: `查看${listing.title}的证据`, exact: true }).last().click();
    await page.getByText("待核实清单", { exact: true }).click();
  };
  for (let round = 1; round <= 2; round++) {
    await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
    await send(page, `check-suggestion-fixture 第${round}次建议`);
    await expect.poll(async () => (await (await page.request.get(`${base}/check-suggestions`)).json()).total_count).toBe(round);
    expect((await (await page.request.get(`${base}/checks`)).json()).total_count).toBe(round === 1 ? 0 : 1);
    await open();
    const suggestion = page.getByRole("region", { name: "核实建议：能否核对屏幕维修记录？", exact: true }).first();
    await suggestion.getByRole("button", { name: "确认保存此问题" }).click();
    await expect(suggestion.getByText(round === 1 ? "已加入清单，仍需核实" : "已对应已有问题，原状态保留", { exact: true })).toBeVisible();
    expect((await (await page.request.get(`${base}/checks`)).json()).total_count).toBe(1);
    if (round === 1) await page.screenshot({ path: info.outputPath("check-suggestion-confirmed.png"), fullPage: true });
    await close();
  }
  await send(page, "check-suggestion-fixture 第3次建议");
  await expect.poll(async () => (await (await page.request.get(`${base}/check-suggestions`)).json()).total_count).toBe(3);
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  await send(page, "partial-change-fixture 更新本地证据");
  await expect(page.getByText("离线夹具已更新一件商品证据", { exact: true })).toBeVisible();
  await page.reload();
  await open();
  const latest = page.getByRole("region", { name: "核实建议：能否核对屏幕维修记录？", exact: true }).first();
  await expect(latest.getByText(/建议依据的要求或证据已变化/)).toBeVisible();
  await expect(latest.getByRole("button", { name: "确认保存此问题" })).toHaveCount(0);
  expect((await (await page.request.get(`${base}/checks`)).json()).total_count).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("new research, saved answer and rename survive reload", async ({ page }) => {
  await page.goto("/tasks/1");
  const mobile = page.getByRole("button", { name: "查看任务" });
  if (await mobile.isVisible()) await mobile.click();
  await page.getByRole("link", { name: "新研究", exact: true }).click();
  await expect(page).toHaveURL(/\/new$/);
  await send(page, "找一台通勤电脑");
  await expect(page).toHaveURL(/\/tasks\/\d+/);
  await expect(page.getByText("已根据保存的证据整理回答。建议核实成色、保修和交易方式。")).toBeVisible();
  await page.getByRole("button", { name: "重命名任务" }).click();
  await page.getByRole("textbox", { name: "任务名称" }).fill("通勤电脑研究");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("heading", { name: "通勤电脑研究" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "通勤电脑研究" })).toBeVisible();
  await expect(page.getByText("已根据保存的证据整理回答。建议核实成色、保修和交易方式。")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("rename saves on click-away and cancels unchanged or escaped drafts", async ({ page }) => {
  await newTask(page, "重命名交互测试");
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  let writes = 0;
  page.on("request", request => { if (request.method() === "PATCH" && /\/api\/tasks\/\d+$/.test(request.url())) writes += 1; });
  await page.getByRole("button", { name: "重命名任务" }).click();
  await page.getByRole("textbox", { name: "任务名称" }).fill("点击外部自动保存");
  await page.locator(".task-header__facts").click();
  await expect(page.getByRole("heading", { name: "点击外部自动保存" })).toBeVisible();
  expect(writes).toBe(1);
  await page.getByRole("button", { name: "重命名任务" }).click();
  await expect(page.getByRole("textbox", { name: "任务名称" })).toHaveValue("点击外部自动保存");
  await page.locator(".task-header__facts").click();
  await expect(page.getByRole("textbox", { name: "任务名称" })).toHaveCount(0);
  expect(writes).toBe(1);
  await page.getByRole("button", { name: "重命名任务" }).click();
  await page.getByRole("textbox", { name: "任务名称" }).fill("不要保存这个名称");
  await page.getByRole("textbox", { name: "任务名称" }).press("Escape");
  await expect(page.getByRole("heading", { name: "点击外部自动保存" })).toBeVisible();
  expect(writes).toBe(1);
  await page.getByRole("button", { name: "重命名任务" }).click();
  await page.getByRole("textbox", { name: "任务名称" }).fill("Enter 保存的名称");
  await page.getByRole("textbox", { name: "任务名称" }).press("Enter");
  await expect(page.getByRole("heading", { name: "Enter 保存的名称" })).toBeVisible();
  expect(writes).toBe(2);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Enter 保存的名称" })).toBeVisible();
});

test("running operation survives navigation and reload; Stop saves no partial answer", async ({ page }) => {
  await newTask(page, "block 等待分析");
  const url = page.url();
  await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible();
  await page.goto("/tasks/2");
  await page.goto(url);
  await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "停止", exact: true }).click();
  await expect(page.getByText("已停止，未保存不完整回答")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  await expect(page.locator(".conversation-item--assistant")).toHaveCount(0);
});

test("approval and rejection restore durable history without collection", async ({ page }) => {
  await newTask(page, "action 补充搜索");
  await expect(page.getByText("确认仅记录请求；点击“执行采集”后才访问闲鱼")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByText("已确认，请核对执行范围")).toBeVisible();
  await send(page, "action 再次请求");
  await page.getByRole("button", { name: "拒绝", exact: true }).click();
  await expect(page.locator('.action-request[data-request-state="rejected"] > summary')).toContainText("已拒绝");
  await page.reload();
  await expect(page.getByText("已确认，请核对执行范围")).toBeVisible();
  await expect(page.locator('.action-request[data-request-state="rejected"] > summary')).toContainText("已拒绝");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("restart and invalid result are explicit and recoverable", async ({ page }) => {
  await page.goto("/tasks/3");
  await expect(page.getByText(/服务重启，任务已中断/)).toBeVisible();
  await newTask(page, "invalid 输出测试");
  await expect(page.getByText("本次分析未完成")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
});

test("preference changes persist through the product UI and refresh", async ({ page }) => {
  await newTask(page, "iPhone 15 Pro 256GB，上海面交，预算3800，电池至少88%");
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  await send(page, "preference-fixture 预算提高到4300，电池至少90%");
  await expect(page.getByText("购买要求已保存，正在按新要求比较已有证据。", { exact: true })).toBeVisible();
  const summary = page.getByText("查看当前购买要求（已更新）", { exact: true });
  await summary.click();
  await expect(summary.locator("..")).toContainText("上海面交，预算4300，电池至少90%");
  const taskId = page.url().split("/").at(-1);
  const saved = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  expect(saved.preference_revisions).toHaveLength(1);
  expect(saved.task.original_goal).toContain("预算3800");
  await page.reload();
  await page.getByText("查看当前购买要求（已更新）", { exact: true }).click();
  const requirements = page.locator("details").filter({ has: page.getByText("查看当前购买要求（已更新）", { exact: true }) });
  await expect(requirements.getByText("iPhone 15 Pro 256GB，上海面交，预算4300，电池至少90%", { exact: true })).toBeVisible();
});

test("answer candidate cards restore after refresh", async ({ page }) => {
  await page.goto("/tasks/1");
  await send(page, "对比已有候选");
  const answer = page.locator(".conversation-item--assistant").last();
  await expect(answer.getByRole("button", { name: /ThinkPad X1 Carbon #01/ })).toBeVisible();
  await page.reload();
  await expect(page.locator(".conversation-item--assistant").last().getByRole("button", { name: /ThinkPad X1 Carbon #01/ })).toBeVisible();
});

test("structured assessment and saved references restore after refresh", async ({ page }) => {
  await page.goto("/tasks/1");
  await send(page, "structured-fixture 要求ThinkPad X1 Carbon，按型号逐项核实");
  const assessment = page.locator(".conversation-item--assistant").last().locator("details").filter({ has: page.locator("summary", { hasText: "已保存的逐项评估" }) });
  await expect(assessment).toContainText("硬性要求：ThinkPad X1 Carbon 型号");
  await expect(assessment).toContainText("符合（据当前证据） · 平台展示");
  await assessment.getByText("查看当时引用的证据（1）", { exact: true }).click();
  await expect(assessment.locator("blockquote")).toContainText("ThinkPad X1 Carbon #01");
  await page.reload();
  await expect(assessment).toContainText("卡片型号符合，实物未核实");
  const saved = await (await page.request.get("/api/tasks/1")).json();
  expect(saved.research.assessment_batches.at(-1).execution_state).toBe("succeeded");
  expect(saved.research.assessment_batches.at(-1).stale).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("history review keeps partial results and restores versioned comparison", async ({ page }, info) => {
  const taskId = info.project.name === "desktop-chromium" ? 4 : 5;
  await page.goto(`/tasks/${taskId}`);
  await send(page, "history-fail-fixture 重新评估全部已保存候选");
  const progress = page.getByRole("region", { name: "历史候选重评进度" }).last();
  await expect(progress).toContainText("候选重评未完成");
  await expect(progress).toContainText("已逐项评估 20 件 · 待处理 35 件");
  await expect(page.getByRole("region", { name: "已保存的候选比较" })).toHaveCount(0);
  await page.reload();
  await expect(progress).toContainText("待处理 35 件");
  await send(page, "history-review-fixture 继续重评历史候选");
  // This turn runs multiple model batches before publishing. Wait for durable
  // completion independently of the previous operation's cached UI status.
  await expect.poll(async () => {
    const history = await (await page.request.get(`/api/tasks/${taskId}/research`)).json();
    return history.reviews.at(-1)?.state;
  }, { timeout: 15000, intervals: [500, 1000] }).toBe("completed");
  const comparison = page.getByRole("region", { name: "已保存的候选比较" }).last();
  await expect(comparison).toContainText("本轮候选比较");
  await expect(comparison).toContainText("已保存范围 55 件 · 已审视 55 件 · 已逐项评估 55 件 · 待处理 0 件");
  await expect(comparison).toContainText("型号有卡片支持，继续核实内存与实物");
  await page.reload();
  await expect(comparison).toContainText("候选变化及原因");
  await send(page, "history-change-fixture 内存至少16GB");
  await expect(page.getByRole("region", { name: "已保存的候选比较" })).toHaveCount(2);
  await expect(page.getByRole("region", { name: "已保存的候选比较" }).first()).toContainText("历史候选比较（要求或证据已变化）");
  await expect(comparison).toContainText("本轮候选比较");
  const saved = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  expect(saved.research.comparisons.at(-1).coverage.assessed_count).toBe(55);
  expect(saved.research.comparisons[0].stale).toBe(true);
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("legacy goal sources and paged research load through the UI", async ({ page }, info) => {
  const taskId = info.project.name === "desktop-chromium" ? 6 : 7;
  await page.goto(`/tasks/${taskId}`);
  await send(page, "legacy-goal-fixture 按这个旧任务的原始要求重评");
  const comparison = page.getByRole("region", { name: "已保存的候选比较" }).first();
  await expect(comparison).toContainText("本轮候选比较");
  const initial = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  expect(initial.research.standards[0].criteria[0].source_refs).toEqual(["task_goal"]);
  expect(initial.research.standards[0].criteria[0].source_message_ids).toEqual([]);
  const messages = await (await page.request.get(`/api/tasks/${taskId}/messages`)).json();
  expect(messages.items).toHaveLength(2);
  for (let n = 0; n < 12; n++) {
    // This case tests paging/reference restoration, not thirteen separate UI
    // send/poll cycles. Prepare durable history through the real offline API.
    const response = await page.request.post(`/api/tasks/${taskId}/messages`,
      {data:{message:`structured-fixture 按原有标准继续核对，第${n + 1}次`}});
    expect(response.ok()).toBe(true);
    const {operation} = await response.json();
    await expect.poll(async()=> (await(await page.request.get(`/api/operations/${operation.id}`)).json()).operation.state,
      {timeout:5000,intervals:[100,250,500]}).toBe('completed');
  }
  await page.reload();
  await expect(page.locator(".conversation-item--assistant")).toHaveCount(13);
  const progress = page.getByRole("region", { name: "研究记录加载进度" });
  await expect(progress).toContainText("已加载评估 10/15 批");
  const bound = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  expect(bound.research.assessment_batches).toHaveLength(10);
  const referencedId = bound.research.comparisons[0].result.ranked_candidates[0].assessment_id;
  expect(bound.research.assessment_batches.some((a: { id: number }) => a.id === referencedId)).toBe(false);
  const referenceResponse = page.waitForResponse(response => response.url().endsWith(`/research/assessments/${referencedId}`) && response.status() === 200);
  await comparison.getByText("查看本次排序引用的评估", { exact: true }).first().click();
  await referenceResponse;
  await expect(comparison).toContainText("卡片支持型号，实物仍需核实");
  await page.getByRole("button", { name: "加载更早研究记录", exact: true }).click();
  await expect(progress).toContainText("已加载评估 15/15 批");
  await page.reload();
  await expect(progress).toContainText("已加载评估 10/15 批");
  await expect(comparison).toContainText("本轮候选比较");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("long task metadata pages preserve current requirements and full totals", async ({ page }, info) => {
  const taskId = info.project.name === "mobile-chromium" ? 9 : 8;
  await page.goto(`/tasks/${taskId}`);
  await expect(page.locator(".task-header__facts")).toContainText("报告23");
  const response = await page.request.get(`/api/tasks/${taskId}`);
  const data = await response.json();
  expect(data.runs).toHaveLength(10);
  expect(data.preference_revisions).toHaveLength(10);
  expect(data.task.effective_goal).toBe("长任务当前目标22");
  expect(data.current_preferences).toContain("早期保留偏好");
  await page.getByText("查看任务记录（需求修订、采集轮次与报告）", { exact: true }).click();
  const progress = page.getByRole("status", { name: "任务记录加载进度" });
  await expect(progress).toContainText("需求修订 10/23");
  await page.getByRole("button", { name: "加载更早任务记录" }).click();
  await expect(progress).toContainText("需求修订 20/23");
  await page.getByRole("button", { name: "加载更早任务记录" }).click();
  await expect(progress).toContainText("需求修订 23/23");
  await expect(page.getByText("长任务需求修订0", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "加载更早任务记录" })).toHaveCount(0);
  await page.reload();
  await page.getByText("查看任务记录（需求修订、采集轮次与报告）", { exact: true }).click();
  await expect(progress).toContainText("需求修订 10/23");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("partial reuse reassesses one candidate and saves fresh group nominations", async ({ page }, info) => {
  const taskId = info.project.name === "mobile-chromium" ? 11 : 10;
  await page.goto(`/tasks/${taskId}`);
  await send(page, "history-review-fixture 完整评估已保存候选");
  await expect.poll(async () => (await (await page.request.get(`/api/tasks/${taskId}`)).json()).research.comparisons.length,
    { timeout: 15000 }).toBe(1);
  const first = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  const changedId = first.research.assessment_batches[0].result.assessments[0].listing_id;
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  await send(page, "partial-change-fixture 更新本地单件证据");
  await expect(page.getByText("离线夹具已更新一件商品证据", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  await send(page, "history-review-fixture 按当前证据重评");
  await expect.poll(async () => (await (await page.request.get(`/api/tasks/${taskId}`)).json()).research.comparisons.length,
    { timeout: 15000 }).toBe(2);
  const data = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  expect(data.research.assessment_batches.at(-1).result.assessments.map((item: { listing_id: number }) => item.listing_id)).toEqual([changedId]);
  expect(data.research.reviews.at(-1).nomination_progress).toEqual({ required: true, total_groups: 3, completed_groups: 3, pending_groups: 0 });
  expect(data.research.comparisons.at(-1).coverage.assessed_count).toBe(55);
  await expect(page.getByText(/重新提名进度：已保存 3\/3 组；提名已完成/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/重新提名进度：已保存 3\/3 组；提名已完成/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("explicit seller replies persist as scoped evidence and retain contradictions", async ({ page }, info) => {
  const taskId = info.project.name === "mobile-chromium" ? 13 : 12;
  await page.goto(`/tasks/${taskId}?tab=candidates`);
  const candidates = await (await page.request.get(`/api/tasks/${taskId}/candidates?limit=4`)).json();
  const listingId = candidates.candidates[0].listing_id;
  await expect(page.getByText(`商品 #${listingId}`, { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "对话", exact: true }).click();
  let completed = 0;
  for (const claim of ["卖家原话：没换过屏", "卖家后来改口：换过屏幕"]) {
    await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
    await page.getByRole("combobox", { name: "消息用途" }).selectOption("seller_reply");
    await page.getByRole("spinbutton", { name: "证据所属商品编号" }).fill(String(listingId));
    await send(page, `seller-evidence-fixture ${claim}`);
    completed += 1;
    await expect.poll(async () => (await (await page.request.get(`/api/tasks/${taskId}`)).json()).research.comparisons.length,
      { timeout: 15000 }).toBe(completed);
    await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  }
  const data = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  expect(data.preference_revision_id).toBe(0);
  const last = data.research.assessment_batches.at(-1);
  expect(last.result.assessments).toHaveLength(1);
  expect(last.result.assessments[0].judgments[0].status).toBe("CONFLICT");
  expect(Object.keys(last.evidence_refs).filter(ref => ref.startsWith("statement:"))).toHaveLength(2);
  await page.reload();
  const boundMessages = page.locator(".conversation-item--user").filter({ hasText: "用户转述卖家答复" });
  await expect(boundMessages).toHaveCount(2);
  await page.getByRole("button", { name: "查看绑定商品证据" }).last().click();
  const evidence = page.getByRole("region", { name: "绑定的用户补充证据" });
  await expect(evidence.getByText("seller-evidence-fixture 卖家原话：没换过屏", { exact: true })).toBeVisible();
  await expect(evidence.getByText("seller-evidence-fixture 卖家后来改口：换过屏幕", { exact: true })).toBeVisible();
  await expect(evidence.getByText(/由用户提供，未经独立核实/)).toBeVisible();
  await page.getByText("待核实清单", { exact: true }).click();
  await page.getByRole("textbox", { name: "新增核实问题" }).fill("这台是否换过屏幕？");
  await page.getByRole("button", { name: "保存问题", exact: true }).click();
  const checkItem = page.getByRole("region", { name: "核实问题：这台是否换过屏幕？", exact: true });
  await expect(checkItem).toBeVisible();
  const statementOptions = await (await page.request.get(`/api/tasks/${taskId}/listings/${listingId}/checks`)).json();
  await checkItem.getByRole("combobox", { name: "关联当前补充" }).selectOption(String(statementOptions.available_statements[0].id));
  await checkItem.getByRole("textbox", { name: "核实备注" }).fill("已经记下改口，面交仍需核对。");
  await checkItem.getByRole("button", { name: "关联补充", exact: true }).click();
  await expect(checkItem.getByText("已记录补充，仍待核实", { exact: true })).toBeVisible();
  await checkItem.getByText("核实记录与来源", { exact: true }).click();
  const reviewPanel = page.getByRole("region", { name: "核实记录：这台是否换过屏幕？", exact: true });
  await reviewPanel.getByRole("combobox", { name: "用户记录状态" }).selectOption("conflict");
  await reviewPanel.getByRole("textbox", { name: "记录说明" }).fill("用户记录：卖家两次说法冲突，需要核对维修记录。");
  await reviewPanel.getByRole("checkbox").nth(0).check();
  await reviewPanel.getByRole("checkbox").nth(1).check();
  await reviewPanel.getByRole("button", { name: "保存用户核实记录" }).click();
  await expect(reviewPanel.getByText("用户记录：存在冲突", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: info.project.name === "mobile-chromium" ? "关闭上下文检查器" : "关闭商品证据", exact: true }).click();
  const users = page.locator(".conversation-item--user").filter({ hasText: "seller-evidence-fixture" });
  await users.last().getByRole("button", { name: "撤回此补充" }).click();
  await expect(users.last().getByText("原文保留，不再作为当前证据；需要恢复请重新发送补充。", { exact: true })).toBeVisible();
  await users.last().getByRole("button", { name: "查看绑定商品证据" }).click();
  await page.getByText("待核实清单", { exact: true }).click();
  await expect(checkItem.getByText(/关联补充已撤回/)).toBeVisible();
  await checkItem.getByText("核实记录与来源", { exact: true }).click();
  await expect(reviewPanel.getByText("来源、问题、要求或商品证据已变化，请重新核实。", { exact: true }).first()).toBeVisible();
  await reviewPanel.getByRole("button", { name: "撤回本条核实记录" }).click();
  await expect(reviewPanel.getByText("用户已撤回记录", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: "已保存的候选比较", exact: true }).last().getByRole("heading"))
    .toHaveText("历史候选比较（要求或证据已变化）");
  await page.screenshot({ path: info.outputPath("candidate-checks-recheck.png"), fullPage: true });
  await checkItem.getByRole("button", { name: "重新核实", exact: true }).click();
  await expect(checkItem.getByRole("button", { name: "重新核实", exact: true })).toHaveCount(0);
  await checkItem.getByRole("button", { name: "暂不跟进此项", exact: true }).click();
  await expect(checkItem.getByText("暂不跟进", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByText("待核实清单", { exact: true }).click();
  await expect(checkItem.getByText("暂不跟进", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: info.project.name === "mobile-chromium" ? "关闭上下文检查器" : "关闭商品证据", exact: true }).click();
  const targetId = candidates.candidates[1].listing_id;
  await users.first().getByRole("button", { name: "更正归属" }).click();
  await users.first().getByRole("spinbutton", { name: "更正后的商品编号" }).fill(String(targetId));
  await users.first().getByRole("button", { name: "保存更正" }).click();
  await expect(users.first().getByText(/受影响的评估需要/)).toBeVisible();
  await page.reload();
  await expect(users.last()).toContainText("已撤回的补充");
  await expect(users.first()).toContainText(`原绑定 #${listingId}`);
  await expect(users.first()).toContainText(`商品 #${targetId}`);
  const oldEvidence = await (await page.request.get(`/api/listings/${listingId}/evidence?task_id=${taskId}`)).json();
  const correctedEvidence = await (await page.request.get(`/api/listings/${targetId}/evidence?task_id=${taskId}`)).json();
  expect(oldEvidence.user_statements).toHaveLength(0);
  expect(correctedEvidence.user_statements[0].statement_text).toBe("seller-evidence-fixture 卖家原话：没换过屏");
  const correctedTask = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  expect(correctedTask.preference_revision_id).toBe(0);
  expect(correctedTask.research.comparisons).toHaveLength(2);
  expect(correctedTask.research.comparisons.at(-1).stale).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("shortlist comparison preserves reasons, checks and evidence after refresh", async ({ page }, info) => {
  await page.goto("/tasks/1");
  await send(page, "compare-cards 对比已有候选");
  const comparison = page.getByRole("region", { name: "候选对比" });
  await expect(comparison.locator(".comparison-card")).toHaveCount(2);
  await expect(comparison.locator(".comparison-card").first()).toContainText("容量与所在地描述完整");
  await expect(comparison.locator(".comparison-card").first()).toContainText("待核实维修史及交易地点");
  await expect(page.locator(".shortlist-full-analysis").last()).not.toHaveAttribute("open");
  await page.reload();
  await expect(comparison.locator(".comparison-card")).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("shortlist-comparison.png"), fullPage: true });
  await comparison.locator(".comparison-card").first().getByRole("button", { name: /的证据/ }).click();
  await expect(page.locator("#listing-evidence-title")).toHaveText("ThinkPad X1 Carbon #01");
});

test("conversation visual states at desktop window sizes", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-chromium", "sizes covered once");
  for (const [width, height] of [[1440, 900], [1024, 768], [1280, 900]]) {
    await page.setViewportSize({ width, height });
    await page.goto("/new");
    await expect(page.getByRole("textbox", { name: "对话输入" })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`conversation-${width}-blank.png`), fullPage: true });
    await send(page, "block 运行状态预览");
    await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`conversation-${width}-running.png`), fullPage: true });
    await page.getByRole("button", { name: "停止", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
    await send(page, "回答预览");
    await expect(page.locator(".conversation-item--assistant")).toHaveCount(1);
    await page.screenshot({ path: info.outputPath(`conversation-${width}-answer.png`), fullPage: true });
    await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
    await send(page, "action 请求预览");
    await expect(page.getByRole("button", { name: "确认", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`conversation-${width}-action.png`), fullPage: true });
  }
});
