import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { projectApi, type ProjectOverview } from '../../api/projectClient';
import { Panel, date } from './projectUi';
import { useContextHref } from './contextNavigation';
import { GoalMonitorReview } from './GoalMonitorReview';

export function ProjectGoalCard({data}:{data:ProjectOverview}) {
  const href=useContextHref(data.project.id),[history,setHistory]=useState(false),[review,setReview]=useState(false);
  const query=useQuery({queryKey:['goal-history',data.project.id,data.goal_context?.current_revision],queryFn:()=>projectApi.goalHistory(data.project.id),enabled:history,retry:false});
  return <Panel className="sp-project-goal">
    <div className="sp-between"><div><h2>当前选购目标 {data.goal_context ? <small>v{data.goal_context.current_revision}</small> : null}</h2></div><Link to={href(`/projects/${data.project.id}?view=overview&editGoal=1`)}>调整目标 →</Link></div>
    <p className="sp-project-goal-text">{data.project.goal}</p>
    <dl className="sp-goal-summary"><div><dt>预算上限</dt><dd>{data.policy.budget === null ? '未设置' : `¥${data.policy.budget.toLocaleString()}`}</dd></div><div><dt>必须条件</dt><dd>{data.policy.hard.join('；') || '未单独设置'}</dd></div><div><dt>个人偏好</dt><dd>{data.policy.soft.join('；') || '未单独设置'}</dd></div></dl>
    {data.goal_context && data.goal_context.current_revision>1 ? <p className="sp-muted">后续研究按当前目标进行。已有商品、收藏和历史研究保留；旧目标报告需重新核对，监控关键词不会自动改变。</p> : null}
    <div className="sp-actions"><button aria-expanded={review} onClick={()=>setReview(!review)}>{review?'收起范围检查':'检查监控是否覆盖目标'}</button><button aria-expanded={history} onClick={()=>setHistory(!history)}>查看历史目标</button></div>
    {review ? <GoalMonitorReview id={data.project.id} goal={data.project.goal} hard={data.policy.hard}/> : null}
    {history ? <section aria-label="历史选购目标"><p className="sp-muted">按版本倒序展示最近100条目标记录。</p>{query.isPending ? <p role="status">正在读取历史目标…</p> : query.isError ? <p role="alert">历史目标暂不可读。<button onClick={()=>void query.refetch()}>重试</button></p> : query.data?.items.map(g=><div className="sp-goal-monitor-item" key={g.revision}><strong>目标 v{g.revision}{g.revision===data.goal_context?.current_revision?' · 当前目标':''}</strong><small> · {date(g.created_at)}</small><p>{g.goal}</p><p>预算：{g.budget===null?'未设置':`¥${g.budget}`} · 必须条件：{g.hard.join('；')||'未设置'} · 偏好：{g.soft.join('；')||'未设置'}</p></div>)}</section> : null}
  </Panel>;
}
