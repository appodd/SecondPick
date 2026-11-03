import { describe, expect, it } from "vitest";
import { contextHref, entryHref, projectReturn, workspaceReturn } from "./contextNavigation";

describe("project context navigation", () => {
  it("preserves list presentation state and its source label", () => {
    const source = "/projects/10?view=products&display=cards&q=M2&state=evaluated&sort=price&page=1&fields=hidden";
    const target = contextHref(10, "/projects/10?view=products&display=market&marketFor=101", source);
    const back = projectReturn(10, new URL(target, "https://secondpick.local").searchParams.get("returnTo"));
    expect(back.label).toBe("返回商品列表");
    const params = new URL(back.href, "https://secondpick.local").searchParams;
    for (const [key, value] of new URL(source, "https://secondpick.local").searchParams) expect(params.get(key)).toBe(value);
  });
  it("names shortlist and overview origins", () => {
    expect(projectReturn(10, "/projects/10?view=shortlist").label).toBe("返回候选清单");
    expect(projectReturn(10, "/projects/10?view=overview").label).toBe("返回研究概览");
  });
  it("rejects external, cross-project, unknown and market origins", () => {
    for (const source of [null, "https://example.com/", "//example.com/", "/projects/11?view=shortlist", "/projects/10?view=products&display=market", "/projects/10?view=unknown", "/projects/10?view=__proto__"]) {
      expect(projectReturn(10, source)).toEqual({ href: "/projects/10?view=products&display=table", label: "返回商品列表" });
    }
  });
  it("retains a bounded safe parent when shortlist opens market, without losing overview", () => {
    const shortlist = contextHref(10, "/projects/10?view=shortlist", "/projects/10?view=overview");
    const market = contextHref(10, "/projects/10?view=products&display=market", shortlist);
    const back = projectReturn(10, new URL(market, "https://secondpick.local").searchParams.get("returnTo"));
    expect(back.label).toBe("返回候选清单");
    expect(projectReturn(10, new URL(back.href, "https://secondpick.local").searchParams.get("returnTo"))).toEqual({ href: "/projects/10?view=overview", label: "返回研究概览" });
    let nested = "/projects/10?view=overview";
    for (let i = 0; i < 8; i++) nested = `/projects/10?view=shortlist&returnTo=${encodeURIComponent(nested)}`;
    expect(projectReturn(10, nested).href.length).toBeLessThan(800);
    expect(projectReturn(10, "/projects/10?view=shortlist&returnTo=https%3A%2F%2Fexample.com").href).not.toContain("example.com");
  });
  it("drops drawer and command parameters and retains an original origin from within market", () => {
    expect(projectReturn(10, "/projects/10?view=shortlist&runtime=1&create=1").href).toBe("/projects/10?view=shortlist");
    const target = contextHref(10, "/projects/10?view=products&display=market&marketFor=102", "/projects/10?view=products&display=market&returnTo=%2Fprojects%2F10%3Fview%3Dshortlist");
    expect(new URL(target, "https://secondpick.local").searchParams.get("returnTo")).toBe("/projects/10?view=shortlist");
  });
  it("settings and legacy detours retain the exact market and monitor view safely", () => {
    const source = "/projects/10?view=products&display=market&marketFor=101&market_chip=M2&q=MacBook&returnTo=%2Fprojects%2F10%3Fview%3Dshortlist";
    const href = entryHref(10, "/settings?section=xianyu", source);
    const back = workspaceReturn(new URL(href, "https://secondpick.local").searchParams.get("returnTo"));
    const params = new URL(back.href, "https://secondpick.local").searchParams;
    expect(back.label).toBe("返回行情分析"); expect(params.get("market_chip")).toBe("M2"); expect(params.get("marketFor")).toBe("101");
    expect(projectReturn(10, "/projects/10?view=monitors&monitor=4&logs=4&run=9&setup=1", 0, true).href).toBe("/projects/10?view=monitors&monitor=4&logs=4&run=9");
    expect(workspaceReturn("https://example.com/projects/10?view=overview").href).toBe("/");
    expect(workspaceReturn(null).label).toBe("返回工作台");
  });
  it("allows a cross-project workspace return and keeps study anchors, without allowing ordinary cross-project sources", () => {
    const href = entryHref(11, "/projects/11?view=research#research-run-22", "/projects/10?view=products&runtime=1");
    const url = new URL(href, "https://secondpick.local");
    expect(url.hash).toBe("#research-run-22");
    expect(projectReturn(11, url.searchParams.get("returnTo"), 0, true).label).toBe("返回运行中心");
    expect(projectReturn(11, "/projects/10?view=overview", 0, true).href).toBe("/projects/11?view=products&display=table");
  });
});
