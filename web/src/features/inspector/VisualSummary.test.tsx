import {cleanup,render,screen,fireEvent} from "@testing-library/react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {afterEach,it,expect,vi} from "vitest";
import {VisualSummary} from "./VisualSummary";
import {VisualEvidence,type VisualView} from "./VisualEvidence";
import {comparisonObservations,importantObservations,validObservations} from "./visualPresentation";
import {visualQuestionScope} from "./visualQuestion";
const hash="a".repeat(64);
function data():VisualView {return {task_id:1,listing_id:2,goal_revision:1,state:"image_observation",approval_allowed:false,approval_blocked_reason:"真实执行关闭",execution_enabled:false,
  images:[{media_id:3,sha256:hash,width:24,height:16,source_url:"https://img.alicdn.com/mock"}],observations:[{id:"visual:2:4:1:abc",listing_id:2,study_id:4,run_id:"1152921504606846980",media_id:3,sha256:hash,
    visible_content:"MOCK 局部磨损",limited_inference:"",uncertainty:"底部未展示",status:"visible",provider:"deepseek",model:"deepseek-flash",review_state:"accepted",independently_verified:false,mode:"mock",freshness:"fresh",subject:"surface",origin:"pixels",source_type:"image_observation",affects_criteria:[],references:[{study_id:5,criterion_id:"soft_1",status:"MET"}]}],rejected_observations:0,unavailable_images:0,failures:[]};}
function show(d:VisualView,element?:React.ReactNode){
  const fetcher=vi.fn(async()=>new Response(JSON.stringify(d),{status:200}));vi.stubGlobal("fetch",fetcher);
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>{element??<VisualSummary taskId={1} listingId={2} select={()=>{}}/>}</QueryClientProvider>);return fetcher;
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it("shows only two important checked findings and opens existing product evidence without a POST",async()=>{
  const d=data();d.observations=[d.observations[0],{...d.observations[0],id:'visual:2:4:2:bbb',visible_content:'MOCK 第二条'},{...d.observations[0],id:'visual:2:4:3:ccc',visible_content:'MOCK 第三条'}];
  const select=vi.fn();const fetcher=show(d,<VisualSummary taskId={1} listingId={2} select={select}/>);
  await screen.findByText(/AI 观察：MOCK 局部磨损/);expect(screen.queryByText(/MOCK 第三条/)).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'查看图片与逐条依据 →'}));expect(select).toHaveBeenCalledWith(2);expect(fetcher).toHaveBeenCalledTimes(1);
});
it.each(['identity','device_count','packaging_print','function','authenticity','repair','other'])("does not rank or compare %s",async subject=>{
  const d=data();d.observations[0].subject=subject;
  show(d,<VisualSummary taskId={1} listingId={2} select={()=>{}} comparison/>);
  await screen.findByText(/缺少可直接比较的当前视觉证据/);expect(screen.queryByText(/AI 观察：MOCK 局部磨损/)).toBeNull();
});
it.each(['stale','invalid','unknown'] as const)("%s cannot masquerade as a current overview finding",async freshness=>{
  const d=data();d.observations[0].freshness=freshness;show(d);await screen.findByText(/暂无关联研究判断/);expect(screen.queryByText(/AI 观察：MOCK 局部磨损/)).toBeNull();
});
it("surfaces uncertainty and pending packaging review without asserting an actual item count",async()=>{
  const d=data();const ob=d.observations[0];d.observations=[{...ob,subject:'packaging_print',review_state:'pending_review',freshness:'stale'},{...ob,id:'visual:2:4:2:ccc',status:'unreadable',visible_content:''}];
  show(d);await screen.findByText(/高影响或待复核观察/);expect(screen.getByText(/看不清或未展示/)).toBeVisible();expect(screen.queryByText(/AI 观察：MOCK 局部磨损/)).toBeNull();
});
it("unlinked low-value descriptions do not become overview conclusions",()=>{const d=data();d.observations[0].references=[];expect(importantObservations(d.observations)).toEqual([]);expect(comparisonObservations(d.observations)).toHaveLength(1);});
it.each(['seller','task','listing','hash','independent','missing','no-topic'])("rejects mismatched or unsupported %s in presentation",fault=>{
  const d=data();const ob=d.observations[0];
  if(fault==='seller')ob.origin='seller_claim';if(fault==='task')d.task_id=99;if(fault==='listing')ob.listing_id=99;if(fault==='hash')ob.sha256='bad';if(fault==='independent')(ob as unknown as {independently_verified:boolean}).independently_verified=true;
  if(fault==='missing')(ob as unknown as {uncertainty:undefined}).uncertainty=undefined;
  if(fault==='no-topic')delete ob.subject;
  const rows=validObservations(d,1,2);expect(fault==='no-topic'?comparisonObservations(rows):rows).toEqual([]);
});
it("research detail filters actual references and offers a draft-only follow-up",async()=>{
  const d=data();const draft=vi.fn();const fetcher=show(d,<VisualEvidence taskId={1} listingId={2} referencedByStudy={5} onQuestion={draft}/>);
  await screen.findByText('MOCK 局部磨损');fireEvent.click(screen.getByRole('button',{name:'就这条观察准备追问'}));expect(draft).toHaveBeenCalledWith(d.observations[0]);
  expect(screen.queryByRole('button',{name:'审查图片分析范围'})).toBeNull();expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('link',{name:'查看来源图片 #3'})).toHaveAttribute('href',expect.stringContaining('sha256='+hash));
});
it("nonreferenced observations are not shown in another text run",async()=>{const d=data();show(d,<VisualEvidence taskId={1} listingId={2} referencedByStudy={9}/>);await screen.findByText(/暂无有效 AI 图片观察/);expect(screen.queryByText('MOCK 局部磨损')).toBeNull();});
it("follow-up uses bounded, labeled uncertain text and never implies the text model received pixels",()=>{const s=visualQuestionScope(data().observations[0]);expect(s.ids).toEqual([2]);expect(s.question).toContain('本次文字追问未附图片');expect(s.question).toContain('未经独立核验');expect(s.question).not.toContain(hash);});
it("missing arrays degrade without invented observations",async()=>{show({task_id:1,listing_id:2} as VisualView);await screen.findByText(/暂无关联研究判断/);expect(screen.queryByText(/AI 观察：/)).toBeNull();});
it("even human-accepted high-impact claims do not become overview facts",()=>{const d=data();d.observations[0].subject='identity';expect(importantObservations(d.observations)).toEqual([]);});
it("details label unobserved files without asserting model inspection",async()=>{const d=data();d.observations=[];show(d,<VisualEvidence taskId={1} listingId={2}/>);await screen.findByText('尚无当前可用观察的本地图片');expect(screen.getByText(/本地文件或浏览器预览不等于模型实际查看/)).toBeInTheDocument();});
