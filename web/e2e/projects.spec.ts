import { test, expect } from "@playwright/test";

test("project pages and evidence drawer stay usable at 1024/1280/1440", async ({
  page,
}) => {
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/projects/10?view=products");
    await expect(page.getByRole("table")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
    await page.locator(".sp-product-cell").first().click();
    await expect(
      page.getByRole("dialog", { name: "商品与卖家证据" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "卖家研究", exact: true }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("dialog", { name: "商品与卖家证据" }),
    ).toHaveCount(0);
  }
});

test('persisted research, favorites, comparison and project creation stay separate',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/projects/10?view=products');await page.getByRole('checkbox',{name:'全选当前页'}).check();
  await expect(page.getByRole('button',{name:'AI 分析选中商品'})).toBeDisabled();
  await page.getByRole('button',{name:'取消选择',exact:true}).click();
  await page.getByRole('checkbox',{name:/^选择 /}).first().check();await page.getByRole('button',{name:'AI 分析选中商品'}).click();
  const agent=page.getByRole('complementary',{name:'SecondPick Agent 对话栏'});
  await agent.getByRole('textbox',{name:'给 Agent 的指令'}).fill('深入调查这件商品');await agent.getByRole('button',{name:'发送',exact:true}).click();
  await agent.getByRole('button',{name:'确认并创建研究任务'}).click();await expect(agent).toContainText(/研究 #\d+ 已创建/);
  await agent.getByRole('link',{name:'查看任务与结果 →'}).click();
  await expect(page.getByRole('heading',{name:/研究 #\d+ · 指定范围/})).toBeVisible();
  await expect(page.locator('.sp-research-history-card').first().getByText('本次研究已完成',{exact:true})).toBeVisible({timeout:15000});
  // An explicitly scoped answer does not become a whole-project report.
  const result=await(await page.request.get('/api/projects/10/overview')).json();expect(result.report).toBeNull();
  await page.getByRole('navigation',{name:'当前项目',exact:true}).getByRole('button',{name:'全部商品',exact:true}).click();
  const favorite=page.getByRole('button',{name:/^收藏商品 #/}).first();const id=Number((await favorite.getAttribute('aria-label'))!.match(/#(\d+)/)![1]);await favorite.click();
  await page.reload();await expect(page.getByRole('button',{name:`取消收藏商品 #${id}`,exact:true})).toBeVisible();
  await page.getByRole('navigation',{name:'当前项目',exact:true}).getByRole('button',{name:'候选清单',exact:true}).click();
  await expect(page.getByRole('region',{name:'候选来源与新鲜度'})).toContainText('尚无报告候选');
  await page.getByRole('checkbox',{name:/^对比 /}).first().click();await expect(page.getByRole('checkbox',{name:/^对比 /}).first()).toBeChecked();await expect(page.getByRole('region',{name:'候选结构化比较'})).toBeVisible();
  await page.getByRole('button',{name:'新建选购项目',exact:true}).first().click();const creator=page.getByRole('dialog',{name:'新建选购项目'});
  await creator.getByLabel('选购目标',{exact:true}).fill('Synthetic collection-only project');await creator.getByLabel('项目名称',{exact:true}).fill('Synthetic independent project');
  await creator.getByRole('button',{name:'仅创建项目',exact:true}).click();await expect(creator).toBeHidden();
  await expect(page.locator('.sp-project-goal-text')).toHaveText('Synthetic collection-only project');
  const projectId=new URL(page.url()).pathname.split('/').at(-1);const created=await(await page.request.get(`/api/projects/${projectId}/overview`)).json();
  expect(created.total).toBe(0);expect(created.report).toBeNull();expect(created.policy.auto_research).toBe(0);expect(created.studies).toEqual([]);
  await page.getByRole('navigation',{name:'当前项目',exact:true}).getByRole('button',{name:'监控任务',exact:true}).click();
  await page.getByRole('button',{name:'新建监控',exact:true}).click();const monitor=page.getByRole('dialog',{name:'监控计划草案'});
  await monitor.getByLabel('监控名称').fill('Synthetic draft only');await monitor.getByLabel('搜索关键词',{exact:true}).fill('Synthetic camera');await monitor.getByRole('button',{name:'预览计划',exact:true}).click();
  await expect(monitor).toContainText('待确认 · 尚未执行');expect((await(await page.request.get(`/api/tasks/${projectId}/monitors`)).json()).items).toEqual([]);expect(errors).toEqual([]);
});
