import { describe, expect, it } from "vitest";
import type { ProjectCard } from "../../api/projectClient";
import { extractSpecs, histogram, initialScope, marketItems, matchesScope, priceSummary } from "./marketAnalysis";
const card = (listing_id: number, title: string, price_value: number | null = 5000) => ({ listing_id, title, price_value, price_text: String(price_value), updated_at: "2026-10-22T02:00:00Z" }) as ProjectCard;
describe("local asking-price analysis", () => {
  it("separates model, chip class, memory and storage without claiming verification", () => {
    expect(extractSpecs("MacBook Pro M2 Pro 16GB 512GB 14寸 2023").specs).toEqual({ model: "MacBook Pro", chip: "M2 pro", memory: "16GB", storage: "512GB", screen: "14 英寸", year: "2023" });
    expect(extractSpecs("MacBook Pro M2 16+512").specs.chip).toBe("M2");
    expect(extractSpecs("MacBook Air M2 16+512").specs.model).toBe("MacBook Air");
  });
  it("does not mistake dedicated GPU memory for system RAM", () => {
    const parsed = extractSpecs("MacBook Pro Intel i9 64G内存 4TB固态 AMD Radeon Pro 5600M 8G独显");
    expect(parsed.specs.memory).toBe("64GB"); expect(parsed.ambiguous).not.toContain("memory");
  });
  it("keeps ambiguous multi-configuration listings out instead of selecting one advertised option", () => {
    const items = marketItems([card(1, "MacBook Pro M1 M2 8GB 16GB 256GB 512GB")]);
    expect(items[0].excluded).toContain("配置不唯一"); expect(items[0].specs.chip).toBeUndefined();
  });
  it("supports phone, ThinkPad and camera families as adapters and leaves unsupported models unknown", () => {
    expect(extractSpecs("iPhone 15 Pro Max 8GB 256GB").specs.model).toBe("iPhone 15 pro max");
    expect(extractSpecs("ThinkPad X1 Carbon i7 16+1T").specs).toMatchObject({ model: "ThinkPad X1 Carbon", chip: "Intel i7", storage: "1TB" });
    expect(extractSpecs("索尼 A7III 单机").specs.model).toBe("Sony A7III");
    expect(extractSpecs("无明确型号的商品").specs.model).toBeUndefined();
  });
  it("uses the goal's M-series preference without mixing in Intel by default", () => {
    const items = marketItems([card(1, "MacBook Pro Intel i7 16GB 512GB"), card(2, "MacBook Pro M2 16GB 512GB")]);
    const scope = initialScope(items, "选一台 M 系列 MacBook Pro");
    expect(scope.chip).toBe("M2"); expect(items.filter(item => matchesScope(item, scope)).map(item => item.card.listing_id)).toEqual([2]);
    expect(initialScope(items.slice(0, 1), "选一台 M 系列 MacBook Pro").chip).toBe("");
  });
  it("chooses an actually observed full configuration and preserves known candidate attributes", () => {
    const items = marketItems([card(1, "MacBook Pro M2 16GB 512GB"), card(2, "MacBook Pro M2 32GB 1TB")]);
    const scope = initialScope(items, "MacBook Pro", items[1]);
    expect(scope).toMatchObject({ chip: "M2", memory: "32GB", storage: "1TB" });
    expect(items.filter(item => matchesScope(item, scope))).toHaveLength(1);
  });
  it("missing chips cannot silently match known chips", () => {
    const items = marketItems([card(1, "MacBook Pro 16GB 512GB"), card(2, "MacBook Pro M2 16GB 512GB")]);
    const scope = initialScope(items, "MacBook Pro", items[0]);
    expect(scope.chip).toBe("__unknown"); expect(matchesScope(items[1], scope)).toBe(false);
  });
  it("does not substitute another family's model when a candidate cannot be identified", () => {
    const items = marketItems([card(1, "标题未说明具体产品"), card(2, "MacBook Pro M2 16GB 512GB")]);
    expect(initialScope(items, "MacBook Pro", items[0]).model).toBe("__unknown");
  });
  it("does not treat starting prices or deposits as a single item's asking price", () => {
    const items = marketItems([{ ...card(1, "iMac i7"), price_text: "¥3000起" }, { ...card(2, "iMac i7"), price_text: "定金¥1000" }]);
    expect(items.every(item => item.excluded)).toBe(true);
  });
  it("treats conflicting purchase/model years as unknown without removing an otherwise unambiguous configuration", () => {
    const item = marketItems([card(1, "MacBook Pro Intel i7 16GB 512GB 2019款 2021购买")])[0];
    expect(item.excluded).toBeUndefined(); expect(item.specs.year).toBeUndefined(); expect(item.ambiguous).toContain("year");
  });
  it("deduplicates IDs, excludes invalid/range/accessory prices, and retains gifts with whole products", () => {
    const items = marketItems([card(1, "iMac i7 16GB 512GB", 2000), card(1, "iMac i7 16GB 512GB", 3000), card(2, "iMac", null), card(3, "iMac", 0), card(4, "iMac", NaN), { ...card(5, "iMac"), price_text: "3000-6000" }, card(6, "MacBook Pro 保护壳", 50), card(7, "MacBook Pro M2 16GB 512GB，赠送保护壳")]);
    expect(items).toHaveLength(7); expect(items.filter(item => !item.excluded).map(item => item.card.listing_id)).toEqual([1, 7]);
    expect(items[0].card.price_value).toBe(3000);
  });
  it("uses the old linear interpolation definition on real priced items", () => {
    const items = marketItems([100, 200, 300, 400].map((price, id) => card(id, "iMac i7", price)));
    expect(priceSummary(items)).toEqual({ count: 4, min: 100, max: 400, q1: 175, median: 250, q3: 325 });
    expect(priceSummary([]).median).toBeNull();
  });
  it("groups equal and adjacent asking prices, and includes the exact upper boundary once", () => {
    const items = marketItems([2999, 3000, 3000, 3100, 4000, 5000, 6000, 7000, 8000].map((price, id) => card(id, "iMac i7", price)));
    const result = histogram(items, items);
    expect(result.bins.length).toBeLessThanOrEqual(10);
    expect(result.bins.reduce((sum, bin) => sum + bin.ids.length, 0)).toBe(9);
    expect(result.bins.at(-1)!.ids).toContain(8);
    expect(result.bins.find(bin => bin.ids.includes(1))!.ids).toContain(2);
  });
  it("does not re-bin when capacity, search or status narrows the same reference basis", () => {
    const items = marketItems([1000, 1500, 2000, 2500, 3000, 3500, 4000].map((price, id) => card(id, "iMac i7", price)));
    const full = histogram(items, items), filtered = histogram(items, items.slice(2, 5));
    expect(filtered.bins.map(bin => [bin.lower, bin.upper])).toEqual(full.bins.map(bin => [bin.lower, bin.upper]));
    expect(filtered.bins.reduce((sum, bin) => sum + bin.ids.length, 0)).toBe(3);
  });
  it("handles empty, single-price and widely spread pools without creating one bin per price", () => {
    expect(histogram([], []).bins).toEqual([]);
    const one = marketItems([card(1, "iMac i7", 5000), card(2, "iMac i7", 5000)]);
    expect(histogram(one, one).bins).toHaveLength(1);
    const wide = marketItems([card(1, "iMac i7", 1), card(2, "iMac i7", 1000000000)]);
    expect(histogram(wide, wide).bins.length).toBeLessThanOrEqual(10);
  });
});
