import { judgmentBasis } from "../conversation/matchEvidence";
import type { DecisionPoint } from "./candidateDecision";
import { judgmentTone } from "./evidenceTone";

export function DecisionEvidence({points,empty,limit=2}:{points:DecisionPoint[];empty:string;limit?:number}) {
  if(!points.length)return <p className="ux2-unknown">{empty}</p>;
  function items(values:DecisionPoint[]){return <ul className="ux2-evidence-list">{values.map(({judgment:j,label,priority},i)=><li key={`${j.criterion_id}:${i}`} data-tone={judgmentTone(j,priority)}><strong>{label}</strong><p>{j.reason}</p><small data-source={j.source_type}>{j.source_type==='seller_claim'?'卖家描述 · 未独立核实':j.status==='UNKNOWN'?'信息不足，尚不能判断':!j.evidence_refs.length?'引用缺失，需核对原判断':judgmentBasis(j)}</small></li>)}</ul>}
  return <>{items(points.slice(0,limit))}{points.length>limit?<details className="sp-copy-help"><summary>其余 {points.length-limit} 项</summary>{items(points.slice(limit))}</details>:null}</>;
}
