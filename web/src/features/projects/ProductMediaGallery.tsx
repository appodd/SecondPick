import {useRef,useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api,request} from '../../api/client';
import {ProductGallery} from './ProductImages';

export type ProductMediaResponse={listing_id:number;state?:string;source_count?:number;local_count?:number;source_signature?:string;preparation_enabled?:boolean;images:{id:number;url:string;created_at:string;source_url?:string;display_url?:string|null;state?:string;sha256?:string|null}[]};
type Preview={ticket:string;media:{id:number;source_url:string}[];expires_at:number;notice:string;model_authorized:false};
export function ProductMediaGallery({taskId,listingId,title,fallback=[]}:{taskId:number;listingId:number;title:string;fallback?:string[]}){
 const client=useQueryClient(),lock=useRef(false);
 const q=useQuery({queryKey:['product-images',taskId,listingId],queryFn:()=>api.getProductImages(taskId,listingId) as Promise<ProductMediaResponse>,retry:false,staleTime:30000,refetchInterval:q=>['waiting','preparing'].includes(q.state.data?.state??'')?2000:false});
 const [selected,setSelected]=useState<number[]>([]),[preview,setPreview]=useState<Preview>(),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const base=`/api/tasks/${taskId}/listings/${listingId}/images`;
 const data=q.data,local=(data?.images??[]).map(i=>i.display_url).filter((s):s is string=>typeof s==='string'&&s.startsWith(base+'/'));
 async function act(execute:boolean){if(lock.current||!data)return;lock.current=true;setBusy(true);setMessage('');
  try{
   if(!execute){const r=await request<Preview>(base+'/prepare-preview',{method:'POST',body:JSON.stringify({media_ids:selected,source_signature:data.source_signature})});setPreview(r);setConsent(false)}
   else if(preview&&consent){const ticket=preview.ticket;setPreview(undefined);setConsent(false);const r=await request<{state:string}>(base+'/prepare',{method:'POST',body:JSON.stringify({ticket,confirmed:true})});setMessage(r.state==='prepared'?'图片已准备；没有上传模型或启动研究。':'图片获取未完成，保留未知；不会自动重试。如需重试请重新授权。');
    await q.refetch();await client.invalidateQueries({queryKey:['project',taskId]});await client.invalidateQueries({queryKey:['visual-evidence',taskId]});await client.invalidateQueries({queryKey:['visual-investigations',taskId]});}
  }catch{setPreview(undefined);setMessage('本次图片操作未完成，已停止；未调用模型。请检查来源或执行门禁，再明确授权。')}
  finally{lock.current=false;setBusy(false)}
 }
 if(q.isPending)return <section className="sp-gallery"><h3>商品图片</h3><p role="status">正在读取图片来源和本地缓存…</p></section>;
 if(!data)return <section className="sp-gallery"><h3>商品图片状态暂不可用</h3><p>无法读取图片列表；这不表示历史没有图片。</p><ProductGallery images={fallback.filter(s=>s.startsWith('/api/tasks/'))} title={title}/><button onClick={()=>q.refetch()}>重试图片列表</button></section>;
 const state=data.state??(data.images.length?'not_prepared':'source_missing');
 return <><ProductGallery key={String(q.dataUpdatedAt)} images={local} title={title} complete state={state} sourceCount={data.source_count??data.images.length} onRefresh={()=>{void q.refetch()}}/>
  {data.images.length?<details className="sp-gallery-prepare"><summary>按需准备图片（只下载，不看图）</summary>
   <p>仅使用已保存的商品链接，最多3张。保留研究暂停状态，不上传模型、不创建 AgentRun；失败不自动重试。</p>
   {!data.preparation_enabled?<p>服务端图片获取尚未授权；已有本地图片仍可浏览。不需要开启 DeepSeek 视觉执行。</p>:null}
   {data.images.map(i=><label key={i.id}><input type="checkbox" disabled={busy||(!selected.includes(i.id)&&selected.length>=3)} checked={selected.includes(i.id)} onChange={e=>{setSelected(e.target.checked?[...selected,i.id]:selected.filter(n=>n!==i.id));setPreview(undefined);setConsent(false)}}/>图片 #{i.id} · {i.state==='local_available'?'已缓存':i.state==='cache_invalid'?'缓存失效':i.state==='fetch_failed'?'上次获取失败':'链接已保存，未准备'}<small>{i.source_url??i.url}</small></label>)}
   <button disabled={busy||!selected.length||!data.preparation_enabled||!data.source_signature} onClick={()=>act(false)}>审查图片获取范围</button>
   {preview?<fieldset disabled={busy}><legend>本次图片获取确认</legend><p>{preview.notice}</p><p>商品 #{listingId}；图片 {preview.media.map(i=>'#'+i.id).join(' → ')}。有效期至 {new Date(preview.expires_at*1000).toLocaleTimeString()}。</p>
    <label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>仅授权获取上述图片，不授权任何模型分析</label><button disabled={!consent||busy} onClick={()=>act(true)}>确认准备图片</button></fieldset>:null}
   {busy?<p role="status">正在处理图片，请勿重复提交…</p>:null}{message?<p role="status">{message}</p>:null}
  </details>:null}
 </>
}
