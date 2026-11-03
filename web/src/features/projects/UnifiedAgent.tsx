import {createContext,useContext,useEffect,useRef,useState,type ReactNode} from 'react';
import {Link,useNavigate,useSearchParams} from 'react-router-dom';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {projectApi,type ProjectOverview} from '../../api/projectClient';
import {request as apiRequest} from '../../api/client';
import {Modal,date,ProductThumbnail} from './projectUi';
import {useGoalContinuity} from './GoalContinuity';
import {useContextHref} from './contextNavigation';
import {agentInstruction,productAgentScope,type AgentScope} from './agentContext';
import {MonitorCreator} from './MonitorCreator';
import {agentIntent} from './agentIntent';
import {MessageCircle,ChevronDown,X} from 'lucide-react';
import './unified-agent.css';

export interface ChatMessage {
 id:number;role:string;content:string;operation_id:number;state:string;error:string|null;created_at:string;references?:number[];
 scope:{ids:number[];goal_revision:number;study_id?:number|null;report_id?:number|null};
}
interface ChatPage{items:ChatMessage[]}
interface AgentState{
 scope:AgentScope|null;data?:ProjectOverview;visible:boolean;planning:boolean;open:(scope?:AgentScope)=>void;close:()=>void;
 finishPlanning:(message?:string)=>void;projectScope:()=>void;draft:string;setDraft:(s:string|((current:string)=>string))=>void;pending:boolean;setPending:(s:boolean)=>void;
 lastStudy?:number;setLastStudy:(id:number)=>void;notice:string;
}
const AgentContext=createContext<AgentState>({scope:null,visible:false,planning:false,open:()=>{},close:()=>{},finishPlanning:()=>{},projectScope:()=>{},draft:'',setDraft:()=>{},pending:false,setPending:()=>{},setLastStudy:()=>{},notice:''});
export const useProjectAgent=()=>useContext(AgentContext);
// Only the open/closed preference is global. No project content lives here.
let dockOpen=false;
export function AgentButton({children,scope,className=''}:{children:ReactNode;scope?:AgentScope;className?:string}){
 const agent=useProjectAgent();return <button className={className} onClick={()=>agent.open(scope)}>{children}</button>;
}
export function ProjectAgentProvider({data,view,selected=[],children}:{data?:ProjectOverview;view:string;selected?:number[];children:ReactNode}){
 const [params]=useSearchParams();
 const [scope,setScope]=useState<AgentScope|null>(null),[visible,setVisible]=useState(dockOpen),[planning,setPlanning]=useState(false);
 const [draft,setDraft]=useState(''),[pending,setPending]=useState(false),[lastStudy,setLastStudy]=useState<number>(),[notice,setNotice]=useState('');
 const lastSelection=useRef({view:'',key:''});
 const thread=useQuery<ChatPage>({queryKey:['project-agent-chat',data?.project.id],queryFn:()=>apiRequest(`/api/projects/${data!.project.id}/agent-chat`),enabled:!!data});
 useEffect(()=>{setScope(null);setDraft('');setPending(false);setPlanning(false);setLastStudy(undefined);setNotice('');lastSelection.current={view:'',key:''}},[data?.project.id]);
 function projectScope(){setScope({role:'interpret',ids:[],label:'整个选购项目'})}
 const rawSelection=view==='products'?selected:view==='shortlist'?(params.get('compare')??'').split(',').filter(Boolean).map(Number):[];
 const selectionKey=rawSelection.join(',');
 const filterKey=view==='products' ? JSON.stringify(['q','state','match','ai','sort'].map(key=>params.get(key)??'')) : '';
 const hasFilters=!!params.get('q')||['state','match','ai'].some(key=>!!params.get(key)&&params.get(key)!=='all');
 useEffect(()=>{
  if(!data)return;
  const previous=lastSelection.current;
  if((view==='products'||view==='shortlist')&&rawSelection.length&&rawSelection.every(id=>data.cards.some(c=>c.listing_id===id))){
   setScope({role:view==='products'?'products':'decision',ids:[...new Set(rawSelection)],label:`正在${view==='products'?'全部商品':'候选清单'}选中的商品`});
  }else if(previous.view===view&&previous.key&& !selectionKey)projectScope();
  lastSelection.current={view,key:selectionKey};
 },[view,selectionKey,data?.project.id]);
 useEffect(()=>{
  if(!data||view!=='products'||rawSelection.length)return;
  if(hasFilters)setScope(productAgentScope(data,params));
  else setScope(current=>current?.filters?{role:'interpret',ids:[],label:'整个选购项目'}:current);
 },[filterKey,selectionKey,data?.project.id]);
 useEffect(()=>{
  if(scope||!data||thread.isPending)return;
  const saved=thread.data?.items.at(-1)?.scope;
  setScope(saved&&saved.ids.every(id=>data.cards.some(c=>c.listing_id===id))?
   {role:'interpret',ids:saved.ids,label:'延续本项目对话',studyId:saved.study_id??undefined,reportId:saved.report_id??undefined}:
   {role:'interpret',ids:[],label:'整个选购项目'});
 },[scope,data?.project.id,thread.data,thread.isPending]);
 function open(value?:AgentScope){
  if(!data)return;
  if(value){
   if(value.role==='planning'){setPlanning(true);setScope({role:'interpret',ids:[],label:'项目监控配置'})}
   else setScope(value);
   if(value.question!==undefined)setDraft(value.question);
  }else if(!scope)projectScope();
  dockOpen=true;setVisible(true);
 }
 function close(){dockOpen=false;setVisible(false)}
 function finishPlanning(message?:string){setPlanning(false);if(message){setNotice(message);setDraft('')}}
 return <AgentContext.Provider value={{data,scope,visible,planning,open,close,finishPlanning,projectScope,draft,setDraft,pending,setPending,lastStudy,setLastStudy,notice}}>{children}</AgentContext.Provider>;
}
export function SharedAgentPanel({select}:{select:(id:number)=>void}){
 const agent=useProjectAgent();
 if(!agent.data)return null;
 return <>
  <button className="ua-floating" hidden={agent.visible} aria-label="打开项目 Agent" title="SecondPick Agent" onClick={()=>agent.open()}><MessageCircle size={23}/><span>Agent</span></button>
  <aside className="ua-dock" hidden={!agent.visible} aria-label="SecondPick Agent 对话栏">
   <header className="ua-dock-header"><strong>SecondPick Agent</strong><button aria-label="收起 Agent" onClick={agent.close}><ChevronDown size={18}/></button></header>
   {agent.scope?<AgentSession data={agent.data} scope={agent.scope} select={select}/>:<p role="status">正在读取项目上下文…</p>}
  </aside>
  {agent.planning?<MonitorPlanning data={agent.data}/>:null}
 </>;
}
function MonitorPlanning({data}:{data:ProjectOverview}){
 const agent=useProjectAgent(),cache=useQueryClient(),navigate=useNavigate();
 const [target,setTarget]=useState(''),[editing,setEditing]=useState(false);
 const query=useQuery({queryKey:['project',data.project.id,'monitors'],queryFn:()=>projectApi.monitors(data.project.id)});
 const existing=query.data?.items.find(w=>String(w.monitor_id)===target);
 if(editing)return <MonitorCreator id={data.project.id} goal={agent.draft||data.project.goal} existing={existing} close={()=>agent.finishPlanning()} saved={async()=>{
  await cache.invalidateQueries({queryKey:['project',data.project.id]});
  agent.finishPlanning(existing?`监控 #${existing.monitor_id} 的配置已保存，没有自动重新采集。`:'监控已按确认的范围创建，请查看实际运行状态。');
  navigate(`/projects/${data.project.id}?view=monitors`);
 }}/>
 return <Modal title="监控配置方案" close={()=>agent.finishPlanning()}><p>先选任务，再检查草案。修改现有任务不会自动重新采集。</p>
  <label>本次监控要求<textarea value={agent.draft} onChange={e=>agent.setDraft(e.target.value)}/></label>
  <label>调整哪项监控<select value={target} onChange={e=>setTarget(e.target.value)}><option value="">请选择</option><option value="new">创建新监控</option>{query.data?.items.map(w=><option key={w.monitor_id} value={w.monitor_id}>{w.name} · {w.monitor.keyword}</option>)}</select></label>
  {query.error?<p role="alert">任务暂不可读取，请稍后重试。</p>:null}
  <button className="sp-primary" disabled={!target||query.isPending||query.isError||target!=='new'&&!existing} onClick={()=>setEditing(true)}>查看可编辑草案</button>
 </Modal>;
}
function AgentSession({data,scope,select}:{data:ProjectOverview;scope:AgentScope;select:(id:number)=>void}){
 const agent=useProjectAgent(),navigate=useNavigate(),contextual=useContextHref(data.project.id),cache=useQueryClient();
 const [review,setReview]=useState(false),[error,setError]=useState('');
 const busy=useRef(false),requestKey=useRef({signature:'',value:''}),reviewBinding=useRef('');
 const box=useRef<HTMLDivElement>(null),input=useRef<HTMLTextAreaElement>(null);
 const ids=[...new Set(scope.ids)],revision=data.goal_context?.current_revision,goal=useGoalContinuity();
 const boundReport=scope.report??(data.report?.id===scope.reportId?data.report:null);
 const boundStudy=data.studies.find(s=>s.id===scope.studyId);
 const invalid=ids.length>20||ids.some(id=>!data.cards.some(c=>c.listing_id===id))||!!scope.filters&&!ids.length;
 const blocked=!!data.policy.paused||!!data.policy.completed||goal.state!=='unversioned';
 const history=useQuery<ChatPage>({queryKey:['project-agent-chat',data.project.id],queryFn:()=>apiRequest(`/api/projects/${data.project.id}/agent-chat`),refetchInterval:agent.visible?2000:false});
 const active=agent.pending||history.data?.items.some(m=>m.role==='user'&&['queued','running'].includes(m.state));
 useEffect(()=>{const el=box.current,last=el?.lastElementChild;if(el&&last)el.scrollTop+=last.getBoundingClientRect().top-el.getBoundingClientRect().top},[history.data?.items.at(-1)?.id,agent.visible]);
 useEffect(()=>{if(agent.visible)input.current?.focus({preventScroll:true})},[agent.visible]);
 useEffect(()=>{setReview(false);setError('')},[ids.join(','),revision,scope.studyId,scope.reportId,scope.report?.id]);
 function source(){return {study_id:scope.studyId,report_id:scope.reportId??scope.report?.id}}
 async function send(confirmed=false){
  if(busy.current||active||!agent.draft.trim())return;
  setError('');const intent=agentIntent(agent.draft);
  if(!confirmed&&intent==='monitor'){agent.open({role:'planning',ids:[],label:'监控方案',question:agent.draft});return}
  if(!confirmed&&intent==='goal'){navigate(contextual(`/projects/${data.project.id}?view=overview&editGoal=1&goalRequest=${encodeURIComponent(agent.draft)}`));return}
  const wholeProject=!confirmed&&intent==='answer'&&/(整个项目|整个选购项目|全项目|整体研究进展)/.test(agent.draft);
  const turnIds=wholeProject?[]:ids,turnSource=wholeProject?{}:source();
  if((!wholeProject&&invalid)||!revision){setError('关联商品或目标已变化，请重新核对范围。');return}
  const binding=JSON.stringify([ids,revision,agent.draft]);
  if(!confirmed&&intent==='research'){reviewBinding.current=binding;setReview(true);return}
  if(confirmed&&(reviewBinding.current!==binding||!ids.length||blocked)){setError('请核对商品范围与研究状态，再确认本次调查。');setReview(false);return}
  busy.current=true;agent.setPending(true);
  const submittedText=agent.draft;
  try{
   const signature=JSON.stringify([confirmed,turnIds,revision,agent.draft,turnSource]);
   if(requestKey.current.signature!==signature)requestKey.current={signature,value:crypto.randomUUID()};
   if(confirmed){
    const result=await projectApi.study(data.project.id,ids,agentInstruction(scope,agent.draft),requestKey.current.value,revision);
    agent.setLastStudy(result.id);setReview(false);agent.setDraft(current=>current===submittedText?'':current);await cache.invalidateQueries({queryKey:['project',data.project.id]});
   }else{
    if(wholeProject)agent.projectScope();
    await apiRequest(`/api/projects/${data.project.id}/agent-chat`,{method:'POST',body:JSON.stringify({message:agent.draft,ids:turnIds,request_key:requestKey.current.value,expected_goal_revision:revision,...turnSource})});
    agent.setDraft(current=>current===submittedText?'':current);await cache.invalidateQueries({queryKey:['project-agent-chat',data.project.id]});
   }
  }catch(e){setError(e instanceof Error?e.message:String(e));void cache.invalidateQueries({queryKey:['project-agent-chat',data.project.id]})}
  finally{busy.current=false;agent.setPending(false)}
 }
 return <section className="ua-session" aria-label="统一 Agent 上下文">
  <div className="ua-project"><strong>{data.project.title}</strong><small>{data.project.goal}</small></div>
  <div className="ua-scope"><span>{ids.length?`本次关联 ${ids.length} 件商品`:scope.filters?'当前筛选没有商品':'围绕整个选购项目'} · 目标 v{revision??'未知'}</span>
   {scope.filters?<small title={scope.filters}>{scope.label}</small>:null}
   {scope.studyId?<small>研究 #{scope.studyId} · {boundStudy?.goal_revision?`研究目标 v${boundStudy.goal_revision}${boundStudy.goal_revision!==revision?'（历史目标）':''}`:'原始目标版本待核对'}</small>:null}{scope.reportId||scope.report?<small>报告 #{scope.reportId??scope.report?.id} · {boundReport?.goal_revision?`报告目标 v${boundReport.goal_revision}${boundReport.goal_revision!==revision?'（历史目标）':''}`:'保留原报告版本'}</small>:null}
   {ids.length?<div className="ua-products">{ids.map(id=>{const card=data.cards.find(c=>c.listing_id===id);return <button key={id} title={card?.title} onClick={()=>select(id)}>{card?<ProductThumbnail card={card}/>:null}<span>#{id} · {card?.title??'商品已不可读取'}</span></button>})}<button className="ua-project-reset" onClick={agent.projectScope}><X size={12}/>聊整个项目</button></div>:null}
   {invalid?<p role="alert">商品范围暂不可用；请重新选择，或<button className="ua-project-reset" onClick={agent.projectScope}>聊整个项目</button>。</p>:null}
  </div>
  <div ref={box} className="ua-thread" role="log" aria-live="polite" aria-label="项目对话">
   {history.isPending?<p role="status">正在读取对话…</p>:null}{history.error?<p role="alert">对话暂不可读取，输入已保留。<button onClick={()=>void history.refetch()}>重新读取</button></p>:null}
   {!history.isPending&&!history.data?.items.length?<p className="ua-empty">可以直接问项目进展、比较商品，或说说想继续调查什么。</p>:null}
   {history.data?.items.map(m=><article key={m.id} className={`ua-message ua-${m.role}`}><header><strong>{m.role==='user'?'你':'SecondPick Agent'}</strong><time>{date(m.created_at)}</time></header><p>{m.content}</p>
    <small>{m.scope.ids.length?m.scope.ids.map(id=>'#'+id).join(' · '):'项目问题'} · 目标 v{m.scope.goal_revision}{m.scope.study_id?` · 研究 #${m.scope.study_id}`:''}{m.scope.report_id?` · 报告 #${m.scope.report_id}`:''}{m.scope.goal_revision!==revision?'（历史目标）':''}</small>
    {m.role==='user'&&['queued','running'].includes(m.state)?<p role="status">正在回答…</p>:null}
    {m.role==='user'&&['failed','interrupted'].includes(m.state)?<p role="status">{m.error||'本次回答已中断，没有自动重试。'}</p>:null}
    {m.role==='assistant'&&m.references?.length?<div className="sp-actions">{m.references.map(id=><button key={id} onClick={()=>select(id)}>商品 #{id}</button>)}</div>:null}
   </article>)}
  </div>
  {agent.lastStudy?<aside className="ua-linked-study">研究 #{agent.lastStudy} 已创建。<Link to={contextual(`/projects/${data.project.id}?view=research#research-run-${agent.lastStudy}`)}>查看任务与结果 →</Link></aside>:null}
  {agent.notice?<p role="status" className="ua-notice">{agent.notice}</p>:null}
  {review?<aside className="ua-research-review"><strong>准备这次调查</strong><p>{ids.length?ids.map(id=>'#'+id).join('、'):'请先在商品页选择要调查的商品。'}</p><p>{agent.draft}</p><p className="sp-muted">沿用当前选购目标，补充本次研究重点；不会修改项目目标或自动研究设置。永久调整条件请使用“调整选购目标”。</p><small>先研究已保存证据；补采与外部调查仍需另行确认。</small>{blocked?<p role="status">当前研究已暂停，可继续普通问答或查看已有结果。</p>:null}<div className="sp-actions"><button className="sp-primary" disabled={active||blocked||!ids.length||invalid} onClick={()=>void send(true)}>确认并创建研究任务</button><button onClick={()=>setReview(false)}>暂不调查</button></div></aside>:null}
  {error?<p role="alert" className="sp-error">{error}</p>:null}
  <form className="ua-composer" onSubmit={e=>{e.preventDefault();void send()}}><textarea ref={input} aria-label="给 Agent 的指令" placeholder="继续提问，或告诉我想调查、调整什么…" rows={2} maxLength={6000} value={agent.draft} onChange={e=>{agent.setDraft(e.target.value);setReview(false)}}/><button className="sp-primary" disabled={!!active||invalid||!revision||!agent.draft.trim()}>{active?'正在处理…':'发送'}</button></form>
 </section>;
}
