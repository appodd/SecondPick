import type { ProjectCard } from "../../api/projectClient";

export const dimensions = ["model", "chip", "memory", "storage", "screen", "year"] as const;
export type Dimension = typeof dimensions[number];
export type Specs = Partial<Record<Dimension, string>>;
export type MarketScope = Record<Dimension, string>;
export const dimensionNames: Record<Dimension, string> = { model: "商品系列", chip: "处理器 / 芯片", memory: "运行内存", storage: "存储容量", screen: "屏幕尺寸", year: "标题年份" };
export function modelDimensions(model: string): readonly Dimension[] {
  if (/^Sony |^DJI Pocket/.test(model)) return ["model", "year"];
  if (/^iPhone /.test(model)) return ["model", "memory", "storage", "year"];
  if (/^Mac (mini|studio)/.test(model)) return ["model", "chip", "memory", "storage", "year"];
  return dimensions;
}
// Small, extendable title adapters, not an AI model or a verified configuration schema.
const families = [
  { expression: /\bmac\s*book\s*(pro|air)\b/gi, name: (m: RegExpMatchArray) => `MacBook ${m[1].toLowerCase() === "pro" ? "Pro" : "Air"}` },
  { expression: /\bi\s*mac\b/gi, name: () => "iMac" },
  { expression: /\bmac\s*(mini|studio)\b/gi, name: (m: RegExpMatchArray) => `Mac ${m[1].toLowerCase()}` },
  { expression: /\biphone\s*(\d{1,2})\s*(pro\s*max|pro|plus|mini)?\b/gi, name: (m: RegExpMatchArray) => `iPhone ${m[1]}${m[2] ? ` ${m[2].replace(/\s+/g, " ").toLowerCase()}` : ""}` },
  { expression: /\bthinkpad\s*(x\d+|t\d+|p\d+)\s*(carbon)?\b/gi, name: (m: RegExpMatchArray) => `ThinkPad ${m[1].toUpperCase()}${m[2] ? " Carbon" : ""}` },
  { expression: /(?:sony|索尼)\s*(a\d+[a-z0-9]*)\b/gi, name: (m: RegExpMatchArray) => `Sony ${m[1].toUpperCase()}` },
  { expression: /\bdji\s*(?:osmo\s*)?pocket\s*(\d)\b/gi, name: (m: RegExpMatchArray) => `DJI Pocket ${m[1]}` },
];
export function extractSpecs(title: string): { specs: Specs; ambiguous: Dimension[] } {
  const values: Record<Dimension, Set<string>> = Object.fromEntries(dimensions.map(key => [key, new Set<string>()])) as Record<Dimension, Set<string>>;
  const add = (key: Dimension, value: string) => values[key].add(value);
  for (const family of families) for (const match of title.matchAll(family.expression)) add("model", family.name(match));
  for (const match of title.matchAll(/\bm\s*([1-5])\s*(pro|max|ultra)?\b/gi)) add("chip", `M${match[1]}${match[2] ? ` ${match[2].toLowerCase()}` : ""}`);
  for (const match of title.matchAll(/\bi\s*([3579])(?:-\d{4,5}[a-z]*)?\b/gi)) add("chip", `Intel i${match[1]}`);
  if (/(?:\bintel\b|英特尔)/i.test(title) && ![...values.chip].some(value => value.startsWith("Intel"))) add("chip", "Intel（型号未明确）");
  for (const match of title.matchAll(/(?:ryzen|锐龙)\s*([3579])\b/gi)) add("chip", `Ryzen ${match[1]}`);
  // Do not interpret generic 128G as RAM or VRAM such as "8G独显" as system memory.
  for (const match of title.matchAll(/(?:内存|ram)\s*(\d{1,3})\s*(?:gb|g)?\b|(\d{1,3})\s*(?:gb|g)\s*(?:运行)?内存/gi)) add("memory", `${match[1] ?? match[2]}GB`);
  for (const match of title.matchAll(/(?<![\d.])(8|12|16|18|24|32|36|48|64|96)\s*(?:gb|g)(?![a-z\d])/gi)) {
    const at = match.index!;
    if (!/(?:显卡|显存|gpu)\s*[:：]?\s*$/i.test(title.slice(Math.max(0, at - 8), at)) && !/^\s*(?:独显|显存|显卡)/.test(title.slice(at + match[0].length))) add("memory", `${match[1]}GB`);
  }
  for (const match of title.matchAll(/(?<!\d)(128|256|512)\s*(?:gb|g)(?![a-z\d])|(?<![\d.])(1|2|4|8)\s*(?:tb|t)(?![a-z\d])/gi)) add("storage", match[1] ? `${match[1]}GB` : `${match[2]}TB`);
  for (const match of title.matchAll(/(?<!\d)(8|12|16|24|32|36|48|64|96)\s*[+\/]\s*(128|256|512|[1248]\s*t(?:b)?)(?!\d)/gi)) {
    add("memory", `${match[1]}GB`); add("storage", /t/i.test(match[2]) ? `${match[2].replace(/\s|b/gi, "").toUpperCase()}B` : `${match[2]}GB`);
  }
  for (const match of title.matchAll(/\b(20[12]\d)\b/g)) add("year", match[1]);
  for (const match of title.matchAll(/(?<!\d)(1[234567]|2[147]|13\.3|15\.4|15\.6|16\.2)\s*(?:寸|英寸|inch)/gi)) add("screen", `${match[1]} 英寸`);
  const specs: Specs = {}, ambiguous: Dimension[] = [];
  for (const key of dimensions) if (values[key].size === 1) specs[key] = [...values[key]][0]; else if (values[key].size > 1) ambiguous.push(key);
  return { specs, ambiguous };
}

export interface MarketItem { card: ProjectCard; specs: Specs; ambiguous: Dimension[]; excluded?: string }
export function marketItems(cards: ProjectCard[]): MarketItem[] {
  return [...new Map(cards.map(card => [card.listing_id, card])).values()].map(card => {
    const parsed = extractSpecs(card.title);
    const price = card.price_value;
    let excluded: string | undefined;
    if (price === null || !Number.isFinite(price) || price <= 0) excluded = "无有效正数挂牌价";
    else if (/起|定金|订金|首付|每[月天]|\/(?:月|天)|^\s*[¥￥]?\s*-/.test(card.price_text ?? "")) excluded = "挂牌价为起价、定金、租价或无效报价";
    else if (/\d\s*[-~～至]\s*\d/.test(card.price_text ?? "")) excluded = "挂牌价为区间，无法确定单件价格";
    else if (/^\s*(?:求购|回收|出租|租赁|维修服务|维修报价|定金|订金)/.test(card.title) || /(?:仅售|只卖|单卖).{0,6}(?:保护壳|电脑包|转接头|扩展坞|屏幕总成|电源适配器)/.test(card.title)
      || (/(?:保护壳|电脑包|转接头|扩展坞|屏幕总成|电源适配器)/.test(card.title.slice(0, 40).split(/[，,。；;\n]/)[0]) && !/(?:赠送|附赠|赠品|不含|不带|配件齐全)/.test(card.title.slice(0, 40)))) excluded = "标题明确为服务、配件或非整机报价";
    else if (parsed.ambiguous.some(key => ["model", "chip", "memory", "storage"].includes(key))) excluded = `标题配置不唯一：${parsed.ambiguous.map(key => dimensionNames[key]).join("、")}`;
    return { card, ...parsed, excluded };
  });
}
export function matchesScope(item: MarketItem, scope: MarketScope) {
  return dimensions.every(key => !scope[key] || scope[key] === "__all" || (scope[key] === "__unknown" ? !item.specs[key] : item.specs[key] === scope[key]));
}
export function initialScope(items: MarketItem[], goal: string, candidate?: MarketItem): MarketScope {
  const target = candidate?.specs ?? extractSpecs(goal).specs;
  if (!candidate && target.chip === "Intel（型号未明确）") delete target.chip;
  const usable = items.filter(item => !item.excluded);
  const modelCounts = new Map<string, number>();
  for (const item of usable) if (item.specs.model) modelCounts.set(item.specs.model, (modelCounts.get(item.specs.model) ?? 0) + 1);
  const model = candidate ? target.model ?? "__unknown" : target.model ?? [...modelCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0] ?? "";
  let pool = usable.filter(item => item.specs.model === model);
  if (!candidate && /m\s*系列/i.test(goal)) pool = pool.filter(item => item.specs.chip?.startsWith("M"));
  if (!candidate && /intel|英特尔/i.test(goal)) pool = pool.filter(item => item.specs.chip?.startsWith("Intel"));
  const core = target.chip ? pool.filter(item => item.specs.chip === target.chip) : pool;
  // Choose one actually observed configuration, not independent modal values that may not coexist.
  const grouped = new Map<string, { item: MarketItem; count: number }>();
  for (const item of core) {
    const key = dimensions.map(d => item.specs[d] ?? "").join("|");
    const saved = grouped.get(key); grouped.set(key, { item, count: (saved?.count ?? 0) + 1 });
  }
  const common = [...grouped.values()].sort((a, b) => b.count - a.count || a.item.card.listing_id - b.item.card.listing_id)[0]?.item.specs ?? {};
  const relevant = modelDimensions(model);
  return Object.fromEntries(dimensions.map(key => [key, !relevant.includes(key) ? "__all" : key === "model" ? model : target[key] ?? (key === "chip"
    ? candidate ? "__unknown" : common[key] ?? (/m\s*系列/i.test(goal) || pool.some(item => item.specs.chip) ? "" : "__unknown")
    : candidate ? "__all" : common[key] ?? "__all")])) as MarketScope;
}
export function quantile(sorted: number[], fraction: number): number | null {
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * fraction, lower = Math.floor(position), upper = Math.ceil(position);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}
export function priceSummary(items: MarketItem[]) {
  const values = items.map(item => item.card.price_value!).sort((a, b) => a - b);
  return { count: values.length, min: values[0] ?? null, max: values.at(-1) ?? null, q1: quantile(values, .25), median: quantile(values, .5), q3: quantile(values, .75) };
}
function niceStep(raw: number) {
  const power = 10 ** Math.floor(Math.log10(Math.max(raw, 1))), ratio = raw / power;
  return Math.max(1, (ratio <= 1 ? 1 : ratio <= 2 ? 2 : ratio <= 5 ? 5 : 10) * power);
}
export function histogram(basis: MarketItem[], items: MarketItem[]) {
  const values = basis.map(item => item.card.price_value!).filter(value => Number.isFinite(value) && value > 0);
  if (!values.length) return { bins: [], step: 0, min: 0, max: 0 };
  const min = Math.min(...values), max = Math.max(...values), step = niceStep((max - min) / 8 || max / 10);
  const start = Math.floor(min / step) * step, end = Math.max(start + step, Math.ceil(max / step) * step);
  const length = Math.max(1, Math.round((end - start) / step));
  const bins = Array.from({ length }, (_, i) => ({ lower: start + i * step, upper: start + (i + 1) * step, ids: [] as number[] }));
  for (const item of items) {
    const index = Math.min(length - 1, Math.max(0, Math.floor((item.card.price_value! - start) / step)));
    bins[index].ids.push(item.card.listing_id);
  }
  return { bins, step, min: start, max: end };
}
export const marketHref = (project: number, listing?: number) => `/projects/${project}?view=products&display=market${listing === undefined ? "" : `&marketFor=${listing}`}`;
