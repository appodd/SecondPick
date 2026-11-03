import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VisionSettings, type VisionStatus, type VisionProfile } from "./VisionSettings";
let state: VisionStatus;
let requests: {url:string;method:string;body:Record<string,unknown>}[];
let fail = false;
const profile = (id:string,current=false):VisionProfile => ({id,current,revision:1,provider:'deepseek',model:'deepseek-flash',timeout_seconds:300,max_output_tokens:3000,key_configured:true,capability_declared:true,verification:{state:'unverified'}});
beforeEach(()=>{
 state={revision:0,enabled:false,current_id:'first',storage:'windows_dpapi',profiles:[profile('first',true),profile('second')],providers:[{id:'deepseek',models:['deepseek-flash'],endpoint:'https://api.deepseek.com/responses'}]};
 requests=[];fail=false;vi.spyOn(window,'confirm').mockReturnValue(true);
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  const method=init?.method ?? 'GET', body=JSON.parse(String(init?.body ?? '{}'));requests.push({url,method,body});
  if(method!=='GET') {
   if(fail) return new Response(JSON.stringify({error:{code:'verification_failed',message:'验证未通过，原模型保留。'}}),{status:400});
   const id=url.split('/')[4];
   if(url.endsWith('/feature'))state.enabled=body.enabled;
   else if(url.endsWith('/select')){state.current_id=id;state.profiles.forEach(p=>p.current=p.id===id);}
   else if(url.endsWith('/verify'))state.profiles.find(p=>p.id===id)!.verification={state:'verified'};
   else if(method==='DELETE'){state.profiles=state.profiles.filter(p=>p.id!==id);if(state.current_id===id)state.current_id=null;}
   else if(method==='POST'){state.profiles.push({...profile('new'),...body.config});}
   else if(method==='PATCH'){Object.assign(state.profiles.find(p=>p.id===id)!,body.config);}
   state.revision++;
  }
  return new Response(JSON.stringify(state),{status:200});
 }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});
async function open(){render(<VisionSettings/>);await screen.findByRole('button',{name:'添加配置'});await screen.findByText('当前模型',{exact:true});}
const card=(id:string)=>screen.getAllByRole('article')[id==='first'?0:1];
describe('multiple vision configurations',()=>{
 it('loads real catalog metadata only, with one global switch and separate cards',async()=>{await open();expect(screen.getAllByRole('article')).toHaveLength(2);expect(screen.getAllByRole('switch')).toHaveLength(1);expect(screen.getByRole('switch')).toHaveAttribute('aria-checked','false');expect(screen.queryByLabelText('服务商')).toBeNull();expect(requests).toEqual([{url:'/api/vision/profiles',method:'GET',body:{}}]);expect(screen.getAllByText('尚未验证')).toHaveLength(2)});
 it('adds a same-provider configuration without enabling or verifying',async()=>{await open();fireEvent.click(screen.getByRole('button',{name:'添加配置'}));fireEvent.change(screen.getByLabelText('API Key'),{target:{value:'SYNTHETIC-KEY-ONLY'}});fireEvent.click(screen.getByRole('button',{name:'保存配置'}));await waitFor(()=>expect(screen.getAllByRole('article')).toHaveLength(3));expect(requests[1].method).toBe('POST');expect(requests[1].body.config).not.toHaveProperty('enabled');expect(requests[1].body).toHaveProperty('key','SYNTHETIC-KEY-ONLY');expect(state.enabled).toBe(false);expect(window.confirm).not.toHaveBeenCalled();expect(document.body.textContent).not.toContain('SYNTHETIC-KEY-ONLY');expect(screen.queryByLabelText('服务商')).toBeNull()});
 it('blank editing preserves secret and returns to cards',async()=>{await open();fireEvent.click(within(card('first')).getByRole('button',{name:'修改配置'}));expect(screen.getByLabelText(/留空保留/)).toHaveValue('');fireEvent.click(screen.getByRole('button',{name:'保存配置'}));await waitFor(()=>expect(screen.queryByLabelText('服务商')).toBeNull());expect(requests[1].method).toBe('PATCH');expect(requests[1].body).not.toHaveProperty('key');expect(window.confirm).not.toHaveBeenCalled()});
 it('selecting while disabled does not verify or turn feature on',async()=>{await open();fireEvent.click(screen.getByRole('button',{name:'设为当前模型'}));await waitFor(()=>expect(state.current_id).toBe('second'));expect(requests[1].body.verification_confirmed).toBe(false);expect(state.enabled).toBe(false);expect(window.confirm).not.toHaveBeenCalled();expect(within(card('second')).getByText('当前模型')).toBeVisible()});
 it('enable requires informed connection confirmation and uses backend state',async()=>{await open();fireEvent.click(screen.getByRole('switch'));await waitFor(()=>expect(screen.getByRole('switch')).toHaveAttribute('aria-checked','true'));expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('8×8'));expect(requests[1].url).toBe('/api/vision/feature');expect(requests[1].body.verification_confirmed).toBe(true)});
 it('cancelled confirmation does not send any request',async()=>{await open();vi.mocked(window.confirm).mockReturnValue(false);fireEvent.click(screen.getByRole('switch'));expect(requests).toHaveLength(1);expect(state.enabled).toBe(false)});
 it('enable failure stays off and reports reason, with no retry',async()=>{await open();fail=true;fireEvent.click(screen.getByRole('switch'));await screen.findByRole('alert');await waitFor(()=>expect(requests).toHaveLength(3));expect(screen.getByRole('switch')).toHaveAttribute('aria-checked','false');expect(screen.getByRole('alert')).toHaveTextContent('验证未通过');expect(requests.filter(r=>r.method!=='GET')).toHaveLength(1)});
 it('failed enabled switch preserves old current model',async()=>{state.enabled=true;await open();fail=true;fireEvent.click(screen.getByRole('button',{name:'设为当前模型'}));await screen.findByRole('alert');expect(state.current_id).toBe('first');expect(screen.getByRole('switch')).toHaveAttribute('aria-checked','true');expect(requests[1].body.verification_confirmed).toBe(true)});
 it('editing active current model verifies before replacing',async()=>{state.enabled=true;await open();fireEvent.click(within(card('first')).getByRole('button',{name:'修改配置'}));fireEvent.change(screen.getByLabelText('模型 ID'),{target:{value:'deepseek-flash-v2'}});fireEvent.click(screen.getByRole('button',{name:'保存配置'}));await waitFor(()=>expect(screen.queryByLabelText('服务商')).toBeNull());expect(window.confirm).toHaveBeenCalled();expect(requests[1].body.verification_confirmed).toBe(true)});
 it('explicit verify does not enable feature',async()=>{await open();fireEvent.click(within(card('first')).getByRole('button',{name:'重新验证'}));await screen.findByText('连接已验证');expect(state.enabled).toBe(false);expect(requests[1].url).toContain('/first/verify')});
 it('closing keeps every configuration and sends no verification',async()=>{state.enabled=true;await open();fireEvent.click(screen.getByRole('switch'));await waitFor(()=>expect(screen.getByRole('switch')).toHaveAttribute('aria-checked','false'));expect(screen.getAllByRole('article')).toHaveLength(2);expect(window.confirm).not.toHaveBeenCalled();expect(requests[1].body.enabled).toBe(false)});
 it('deleting active current is disabled, confirmed inactive deletion uses stable id',async()=>{state.enabled=true;await open();expect(screen.getByRole('button',{name:'删除配置 first'})).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'删除配置 second'}));await waitFor(()=>expect(screen.getAllByRole('article')).toHaveLength(1));expect(requests[1].url).toBe('/api/vision/profiles/second');expect(requests[1].body.confirmed).toBe(true)});
 it('empty catalog offers add and cannot enable',async()=>{state.profiles=[];state.current_id=null;render(<VisionSettings/>);await screen.findByText('还没有视觉模型配置');expect(screen.getByRole('switch')).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'添加第一个配置'}));expect(screen.getByLabelText('API Key')).toBeRequired();expect(screen.getByText('高级设置').closest('details')).not.toHaveAttribute('open')});
 it('failed initial read exposes no fake cards and can refresh safely',async()=>{vi.mocked(fetch).mockRejectedValueOnce(new Error('SYNTHETIC-SECRET'));render(<VisionSettings/>);await screen.findByRole('alert');expect(screen.queryByRole('article')).toBeNull();expect(document.body.textContent).not.toContain('SYNTHETIC-SECRET');fireEvent.click(screen.getByRole('button',{name:'刷新状态'}));await screen.findByText('当前模型',{exact:true});expect(requests.every(r=>r.method==='GET')).toBe(true)});
});
