import { useRef, useState, useEffect } from "react";
import { ImageOff, X, ZoomIn, ZoomOut, ChevronLeft, ChevronRight } from "lucide-react";
import "./product-images.css";

export function imageSource(value?: string | null) {
  if (!value) return undefined;
  try {
    const url = new URL(value, window.location.origin);
    if (url.username || url.password || !["http:", "https:"].includes(url.protocol)) return undefined;
    return url.href;
  } catch { return undefined; }
}

export function ProductImage({ src, title, large = false, contain = false, state }: {
  src?: string | null; title: string; large?: boolean; contain?: boolean;state?:string;
}) {
  const safe = imageSource(src);
  const [failed, setFailed] = useState<string>();
  const [loaded,setLoaded]=useState<string>();
  const label=safe?'图片加载失败':({source_missing:'来源未提供图片',not_prepared:'图片链接已保存，待准备',waiting:'封面等待准备',preparing:'封面正在准备',fetch_failed:'图片获取失败',cache_invalid:'图片缓存失效'} as Record<string,string>)[state??'']??'暂无商品图片';
  return <span title={!safe||failed===safe?label:undefined} className={`sp-product-photo ${large ? "large" : ""} ${contain ? "contain" : ""} ${!safe?'is-empty':''}`}>
    {safe && failed !== safe ? <>{loaded!==safe?<span className="sp-photo-loading" role="status" aria-label="商品图片加载中"/>:null}<img src={safe} alt={title} loading="lazy" decoding="async" referrerPolicy="no-referrer" onLoad={()=>setLoaded(safe)} onError={() => setFailed(safe)} /></>
      : <span className="sp-photo-fallback" role="img" aria-label={`${title}：${label}`}><ImageOff size={large ? 24 : 20} aria-hidden="true" />{large ? <small>{label}</small> : null}</span>}
  </span>;
}

function PreviewImage({ src, title, zoom }: { src: string; title: string; zoom: number }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <div className="sp-preview-fallback"><span className="sp-photo-fallback" role="img" aria-label={`${title}：图片加载失败`}><ImageOff size={32} /><small>图片暂不可用</small></span></div>;
  return <img src={src} alt={title} referrerPolicy="no-referrer" style={{ width: `${zoom * 100}%`, maxHeight: zoom === 1 ? "70vh" : undefined }} onError={() => setFailed(true)} />;
}

export function ProductGallery({ images, title, complete = false, state, sourceCount, onRefresh }: { images: string[]; title: string; complete?: boolean;state?:string;sourceCount?:number;onRefresh?:()=>void }) {
  const urls = [...new Set(images.map(imageSource).filter((url): url is string => !!url))];
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState(1);
  const dialog = useRef<HTMLDialogElement>(null);
  const active = Math.min(index, Math.max(0, urls.length - 1));
  useEffect(() => () => dialog.current?.close(), []);
  function open(next: number) { setIndex(next); setZoom(1); dialog.current?.showModal(); }
  function move(delta: number) { setIndex((active + delta + urls.length) % urls.length); setZoom(1); }
  return <section className="sp-gallery" aria-label="商品图片">
    <div className="sp-between"><h3>商品图片</h3><span>{urls.length} 张可浏览{sourceCount!==undefined?` · ${sourceCount} 条已存来源`:''}</span></div>
    {state==='waiting'||state==='preparing'?<p className="sp-photo-note" role="status">{state==='waiting'?'封面等待后台准备':'正在准备一张封面'}；不调用 AI，无需逐件确认。</p>:null}
    {state==='source_missing'?<p className="sp-photo-note">来源未提供可用商品图片，或历史采集未保存商品图片来源；不是图片加载失败。不会自动补抓历史商品。</p>:!urls.length&&sourceCount&&!['waiting','preparing'].includes(state??'')?<p className="sp-photo-note">已保存图片链接，尚无可浏览缓存。可单独授权准备图片；不需要启用视觉模型。</p>:null}
    {sourceCount!==undefined&&sourceCount>urls.length&&urls.length>0?<p className="sp-photo-note">其余 {sourceCount-urls.length} 条来源尚未准备或缓存不可用；不代表 AI 已查看。</p>:null}
    {!complete ? <p className="sp-photo-note">当前接口仅提供首图，完整图片列表尚未接入。</p> : null}
    {urls.length ? <><button className="sp-gallery-main" aria-label="放大商品首图" onClick={() => open(0)}><ProductImage src={urls[0]} title={title} large contain /><span><ZoomIn size={14} /> 点击预览与放大</span></button>
      {urls.length > 1 ? <div className="sp-gallery-strip">{urls.map((src, i) => <button key={src} aria-label={`预览第 ${i + 1} 张商品图片`} onClick={() => open(i)}><ProductImage src={src} title={`${title} · 图片 ${i + 1}`} /></button>)}</div> : null}</>
      : <ProductImage title={title} large state={state} />}
    {onRefresh?<button onClick={onRefresh}>重新检查图片缓存</button>:null}
    <dialog className="sp-image-viewer" ref={dialog} aria-label="商品图片预览" onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }} onCancel={event => { event.preventDefault(); dialog.current?.close(); }}
      onKeyDown={event => {
        event.stopPropagation();
        if (event.key === "Escape") { event.preventDefault(); dialog.current?.close(); }
        if (event.key === "ArrowLeft" && urls.length > 1) move(-1);
        if (event.key === "ArrowRight" && urls.length > 1) move(1);
      }}>
      <header><strong>{title} · {active + 1}/{urls.length}</strong><button aria-label="关闭图片预览" onClick={() => dialog.current?.close()}><X size={20} /></button></header>
      <div className="sp-image-tools"><button aria-label="上一张图片" disabled={urls.length < 2} onClick={() => move(-1)}><ChevronLeft size={17} /></button><button aria-label="缩小图片" disabled={zoom <= 1} onClick={() => setZoom(zoom - .5)}><ZoomOut size={17} /></button><span>{Math.round(zoom * 100)}%</span><button aria-label="放大图片" disabled={zoom >= 3} onClick={() => setZoom(zoom + .5)}><ZoomIn size={17} /></button><button aria-label="下一张图片" disabled={urls.length < 2} onClick={() => move(1)}><ChevronRight size={17} /></button><a href={urls[active]} target="_blank" rel="noreferrer">打开原图</a></div>
      <div className="sp-image-stage">{urls[active] ? <PreviewImage key={urls[active]} src={urls[active]} title={`${title} · 图片 ${active + 1}`} zoom={zoom} /> : null}<p>图片来自已保存的商品链接；加载失败时可返回图库或查看原始商品。</p></div>
    </dialog>
  </section>;
}
