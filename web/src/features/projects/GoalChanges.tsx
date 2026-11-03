import {conditionValues as clean,containsCondition as contains} from './goalConditionComparison';
type Conditions = {goal:string;budget:number|null;hard:string[];soft:string[]};
const same=(a:string[],b:string[])=>{const x=clean(a),y=clean(b);return x.length===y.length&&x.every(s=>contains(y,s))};
const budget=(value:number|null)=>value===null?'未设置':`¥${value.toLocaleString()}`;

export function GoalChanges({before,after,saved=false,showRetained=false}:{before:Conditions;after:Conditions;saved?:boolean;showRetained?:boolean}) {
  const rows=[
    {name:'预算上限',changed:before.budget!==after.budget,old:[budget(before.budget)],next:[budget(after.budget)],oldEmpty:'未设置',nextEmpty:'未设置'},
    {name:'必须条件',changed:!same(before.hard,after.hard),old:clean(before.hard).filter(s=>!contains(after.hard,s)),next:clean(after.hard).filter(s=>!contains(before.hard,s)),oldEmpty:'无移除项',nextEmpty:'无新增项'},
    {name:'个人偏好',changed:!same(before.soft,after.soft),old:clean(before.soft).filter(s=>!contains(after.soft,s)),next:clean(after.soft).filter(s=>!contains(before.soft,s)),oldEmpty:'无移除项',nextEmpty:'无新增项'},
  ].filter(row=>row.changed);
  const descriptionChanged=before.goal.trim()!==after.goal.trim();
  const retainedHard=clean(before.hard).filter(s=>contains(after.hard,s));
  const retainedSoft=clean(before.soft).filter(s=>contains(after.soft,s));
  const added=[...clean(after.hard).filter(s=>!contains(before.hard,s)),...clean(after.soft).filter(s=>!contains(before.soft,s))];
  const removed=[...clean(before.hard).filter(s=>!contains(after.hard,s)),...clean(before.soft).filter(s=>!contains(after.soft,s))];
  return <section className="sp-goal-changes" aria-label="本次目标变更对比">
    <h3>{saved?'本次已保存的变化':'本次拟修改的变化'}</h3>
    {showRetained && (added.length>0||removed.length>0||before.budget!==after.budget) ? <div className="sp-goal-change-counts" aria-label="条件条目变化统计">{added.length?<span>新增 {added.length} 条</span>:null}{removed.length?<span>移除 {removed.length} 条</span>:null}{before.budget!==after.budget?<span>预算已调整</span>:null}</div> : null}
    {descriptionChanged&&!rows.length ? <p className="sp-muted">目标描述已修改。{!saved?'预算、必须条件和偏好尚无变化，可使用 AI 整理或手动核对下方条件。':''}</p> : null}
    {rows.length ? <div className="sp-goal-diff-table"><table><thead><tr><th scope="col">调整项</th><th scope="col">修改前</th><th scope="col">{saved?'本次保存':'本次拟修改'}</th></tr></thead><tbody>{rows.map(row=><tr key={row.name}><th scope="row">{row.name}</th><td>{row.old.length?row.old.map(s=><div key={s}>{s}</div>):row.oldEmpty}</td><td>{row.next.length?row.next.map(s=><div key={s}>{s}</div>):row.nextEmpty}</td></tr>)}</tbody></table></div> : !descriptionChanged ? <p className="sp-muted">尚未调整已保存的目标与条件。</p> : null}
    {showRetained ? <details className="sp-goal-unchanged"><summary>其余 {retainedHard.length+retainedSoft.length} 条条件未变</summary><section className="sp-goal-retained" aria-label="保留原有条件">{before.budget===after.budget?<p>预算：{budget(before.budget)}</p>:null}<strong>必须条件</strong>{retainedHard.length?<ul>{retainedHard.map(s=><li key={s}>{s}</li>)}</ul>:<p>没有保留的必须条件。</p>}<strong>个人偏好</strong>{retainedSoft.length?<ul>{retainedSoft.map(s=><li key={s}>{s}</li>)}</ul>:<p>没有保留的偏好。</p>}<small>仅合并空白、明确容量单位等格式差异；其他改写仍按新增和移除展示。</small></section></details> : null}
  </section>;
}
