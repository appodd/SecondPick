import { useId } from "react";
import { histogram } from "./marketAnalysis";

export const money = (value: number | null) => value === null || !Number.isFinite(value) ? "—" : `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
export function PriceHistogram({ data, candidatePrice, selectBin }: { data: ReturnType<typeof histogram>; candidatePrice?: number | null; selectBin: (ids: number[]) => void }) {
  const id = useId();
  if (!data.bins.length) return null;
  const left = 45, width = 630, top = 30, height = 180, bottom = top + height;
  const maxCount = Math.max(1, ...data.bins.map(bin => bin.ids.length)), column = width / data.bins.length;
  const candidate = candidatePrice !== undefined && candidatePrice !== null && candidatePrice > 0 && Number.isFinite(candidatePrice) ? candidatePrice : null;
  const x = candidate === null ? null : left + Math.max(0, Math.min(1, (candidate - data.min) / (data.max - data.min))) * width;
  return <div className="sp-market-chart"><svg viewBox="0 0 700 270" role="group" aria-labelledby={id}>
    <title id={id}>本项目样本挂牌价格区间分布，横轴为人民币价格区间，纵轴为商品数量</title>
    {[...new Set([0, Math.ceil(maxCount / 2), maxCount])].map(value => <g key={value}><line x1={left} x2={left + width} y1={bottom - value / maxCount * height} y2={bottom - value / maxCount * height} className="sp-market-gridline" /><text x={left - 10} y={bottom - value / maxCount * height + 4} textAnchor="end">{value}</text></g>)}
    <text x={left} y={16}>数量（件）</text>
    {data.bins.map((bin, index) => {
      const barHeight = bin.ids.length / maxCount * height, label = `${money(bin.lower)}–${money(bin.upper)}${index === data.bins.length - 1 ? "（含上界）" : "（不含上界）"}：${bin.ids.length} 件`;
      return <g key={bin.lower} className="sp-market-bin" role="button" tabIndex={0} aria-label={label} onClick={() => selectBin(bin.ids)} onKeyDown={event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); selectBin(bin.ids); } }}>
        <title>{label}，点击查看样本</title><rect x={left + column * index + 6} y={top} width={Math.max(1, column - 12)} height={height} fill="transparent" />
        <rect className="sp-market-bar" x={left + column * index + 6} y={bottom - barHeight} width={Math.max(1, column - 12)} height={barHeight} rx={5} />
        <text className="sp-market-bar-count" x={left + column * (index + .5)} y={Math.max(25, bottom - barHeight - 7)} textAnchor="middle">{bin.ids.length}</text>
        <text x={left + column * (index + .5)} y={230} textAnchor="middle">{bin.lower.toLocaleString("zh-CN")}</text>
        <text x={left + column * (index + .5)} y={245} textAnchor="middle">–{bin.upper.toLocaleString("zh-CN")}</text>
      </g>;
    })}
    {x !== null ? <g className="sp-market-marker"><line x1={x} x2={x} y1={top - 5} y2={bottom} /><circle cx={x} cy={top - 5} r={4} /><title>当前候选 {money(candidate)}{candidate! < data.min ? "，低于图示下界" : candidate! > data.max ? "，高于图示上界" : ""}</title></g> : null}
    <text x={left + width} y={265} textAnchor="end">挂牌价格区间（元）</text>
  </svg></div>;
}
