import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { projectApi } from '../../api/projectClient';
import { useContextHref } from './contextNavigation';
import { goalMonitorCoverage } from './goalMonitorCoverage';

export function GoalMonitorReview({ id, goal, hard }: { id:number; goal:string; hard:string[] }) {
  const href=useContextHref(id);
  const query=useQuery({queryKey:['goal-monitors',id],queryFn:()=>projectApi.monitors(id),refetchInterval:5000,retry:false});
  const target=href(`/projects/${id}?view=monitors`);
  if(query.isPending)return <p role="status">正在读取现有监控范围…</p>;
  if(query.isError || !query.data)return <div><p role="alert">暂时无法确认监控范围，不将读取失败视为缺少监控。</p><button onClick={()=>void query.refetch()}>重新检查</button><Link to={target}>查看监控任务 →</Link></div>;
  const windows=query.data.items;
  const result=goalMonitorCoverage(goal,hard,windows);
  return <section className="sp-goal-monitor-review" aria-label="目标与监控范围检查">
    <p className="sp-muted">依据已保存的搜索关键词检查，不保证平台搜索结果覆盖全部目标条件；预算、内存等仍需核对。未读取的旧版监控可到监控任务页查看。</p>
    {!result.supported ? <p>当前目标暂不能可靠地自动判断覆盖情况，请核对下方监控关键词。</p> : result.items.map(item=><div className="sp-goal-monitor-item" key={item.model}>
      <strong>{item.model}</strong>
      <p>{item.matching.length ? '已有明确相关的监控，无需重复创建。' : item.possible.length ? '现有宽泛搜索可能覆盖，请核对后决定是否补充。' : '未见明确匹配的搜索范围，可补充一条监控。'}</p>
      {[...item.matching,...item.possible].map(w=><p key={w.monitor_id}>{w.name} · {w.monitor?.keyword} · {w.monitor?.desired_state ? '操作尚未完成' : ['running','waiting'].includes(w.monitor?.state ?? '') && w.runs.some(r=>r.state==='running') ? '已启用' : '未启用或范围已结束，请到监控页核对'}</p>)}
      <div className="sp-actions"><Link to={target}>查看现有监控 →</Link>{!item.matching.length ? <Link to={href(`/projects/${id}?view=monitors&setup=1&draftKeyword=${encodeURIComponent(item.keyword)}`)}>准备{item.possible.length ? '补充' : '创建'} {item.model} 监控 →</Link> : null}</div>
    </div>)}
    <details><summary>查看全部已读取监控（{windows.length} 条）</summary>{windows.length ? windows.map(w=><p key={w.monitor_id}>{w.name}：{w.monitor?.keyword ?? '关键词暂不可读'}</p>) : <p>暂无已保存的工作区监控。</p>}<Link to={target}>管理监控与旧范围 →</Link></details>
    <p className="sp-muted">本次检查不会创建、恢复或暂停监控。若已不再考虑旧型号，请在监控页确认是否暂停旧范围。</p>
  </section>;
}
