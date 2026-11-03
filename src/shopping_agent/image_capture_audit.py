"""Bounded source-shape diagnostics: never save response bodies or URL values."""
import json,re,threading
from urllib.parse import urlsplit


class ImageCaptureAudit:
    def __init__(self,directory,round_id):
        if not re.fullmatch('[0-9a-f]{32}',round_id):raise ValueError('invalid_image_diagnostic_round')
        directory.mkdir(parents=True,exist_ok=True)
        if directory.is_symlink():raise ValueError('unsafe_image_diagnostic_directory')
        if sum(1 for p in directory.glob('image-capture-*.jsonl') if re.fullmatch('image-capture-[0-9a-f]{32}\\.jsonl',p.name))>=8:
            raise OSError('image_diagnostic_round_limit')  # Never delete existing evidence.
        self.path=directory/('image-capture-'+round_id+'.jsonl')
        self.count=0;self.lock=threading.Lock();self.disabled=False
        with self.path.open('x',encoding='utf-8') as f:f.write(json.dumps(dict(version=1,event='start',round_id=round_id,metadata_only=True))+'\n')

    def _write(self,record):
        try:
            with self.lock:
                if self.disabled or self.count>=512 or self.path.is_symlink() or self.path.stat().st_size>=256*1024:return
                raw=json.dumps(dict(version=1,**record),separators=(',',':'))
                if len(raw)>1024:return
                with self.path.open('a',encoding='utf-8') as f:f.write(raw+'\n')
                self.count+=1
        except OSError:self.disabled=True  # Diagnostic failure must not change collection behavior.

    @staticmethod
    def _id(value):
        v=str(value) if isinstance(value,(str,int)) and not isinstance(value,bool) else ''
        return v if v.isascii() and v.isdigit() and len(v)<=50 else None

    @staticmethod
    def _type(value):
        return {str:'string',dict:'object',list:'array',int:'number',float:'number',bool:'boolean',type(None):'null'}.get(type(value),'other')

    def installed(self,hashes):
        allowed={'worker','evidence','pipeline','upstream_parser','upstream_scraper'}
        self._write(dict(event='installed',sha256={k:v for k,v in hashes.items() if k in allowed and isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v)}))

    def shape(self,stage,value):
        if stage not in {'search_rows','detail_imageInfos','search_parsed'}:return
        self._write(dict(event='shape',stage=stage,value_type=self._type(value),count=min(len(value),1000000) if isinstance(value,(list,dict)) else None))

    def image_keys(self,stage,value):
        if stage not in {'search_exContent','detail_itemDO'} or not isinstance(value,dict):return
        def safe(k):
            return isinstance(k,str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,40}',k) and not any(x in k.lower() for x in ('token','cookie','auth','secret','password','header'))
        keys=[]
        for key,item in list(value.items())[:80]:
            if safe(key) and any(x in key.lower() for x in ('image','pic','img')):
                children=[k for k in list(item)[:20] if safe(k)][:6] if isinstance(item,dict) else []
                keys.append(dict(field=key,value_type=self._type(item),child_fields=children))
        self._write(dict(event='image_field_names',stage=stage,fields=keys[:8]))

    def url(self,stage,item_id,value,accepted,*,present=True,index=0):
        if stage not in {'search_picUrl','detail_imageInfos_url'}:return
        reason='accepted' if accepted else 'rejected';scheme='other'
        if not present:reason='missing'
        elif value is None:reason='null'
        elif not isinstance(value,str):reason='unsupported_type'
        elif len(value)>2048:reason='too_long'
        else:
            try:
                p=urlsplit(value);scheme=p.scheme if p.scheme in ('https','http') else 'relative' if not p.scheme else 'other'
                if not accepted:
                    reason=('https_required' if p.scheme!='https' else 'userinfo' if p.username or p.password else
                            'port' if p.port not in (None,443) else 'host_or_format')
            except ValueError:reason='malformed'
        self._write(dict(event='source_image',stage=stage,item_id=self._id(item_id),index=min(max(index,0),30),field_present=bool(present),value_type=self._type(value),scheme=scheme,accepted=bool(accepted),reason=reason))

    def output(self,stage,item):
        if stage not in {'search_output','journal_card','journal_seller_enriched','journal_search_card'} or not isinstance(item,dict):return
        images=item.get('商品图片列表');cover=item.get('商品主图链接')
        self._write(dict(event='output',stage=stage,item_id=self._id(item.get('商品ID')),has_cover=isinstance(cover,str) and bool(cover),image_count=min(len(images),30) if isinstance(images,list) else 0))
