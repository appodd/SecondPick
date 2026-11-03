import { describe, expect, it } from "vitest";
import { onboardingHref, onboardingReturn } from "./onboardingNavigation";

describe("onboarding navigation context", () => {
  it("keeps settings section and safe project presentation state", () => {
    const source = "/settings?section=codex&returnTo=" + encodeURIComponent("/projects/12?view=products&display=card&q=M2&page=3&create=1");
    const back = new URL(onboardingReturn(source), "https://secondpick.local");
    expect(back.searchParams.get("section")).toBe("codex");
    expect(back.searchParams.get("returnTo")).toBe("/projects/12?view=products&display=card&q=M2&page=3");
  });
  it.each([null, "https://example.com", "//example.com/settings", "/onboarding", "/settings/other", "http://[", "/?create=1"])("rejects unsafe or unknown return destinations: %s", value => {
    expect(onboardingReturn(value)).toBe("/");
  });
  it("keeps project views and runtime center, including a bare project URL", () => {
    expect(onboardingReturn("/projects/3")).toBe("/projects/3?view=overview");
    expect(onboardingReturn("/projects/3?view=research&runtime=1")).toBe("/projects/3?view=research&runtime=1");
  });
  it("fresh review starts at zero; resume does not override saved progress", () => {
    const review = new URL(onboardingHref("review", "/settings?section=xianyu"), "https://secondpick.local");
    expect(review.searchParams.get("step")).toBe("0");
    expect(review.searchParams.get("returnTo")).toBe("/settings?section=xianyu");
    expect(onboardingHref("resume", "/projects/3")).not.toContain("step=");
  });
});
