"""Bounded public evidence only; standalone-compatible and entirely offline.

Never retain raw responses, credentials, seller biographies or individual reviews.
The upstream dispatcher receives images, but currently not itemDO.desc/attributes.
Missing fields stay absent rather than being reconstructed from titles.
"""
import math
from collections import OrderedDict
from urllib.parse import urlsplit


SEARCH_FIELDS = ("商品原价", "商品标签", "“想要”人数")
DETAIL_FIELDS = ("商品描述", "商品属性", "商品图片列表", "商品主图链接", "浏览量")
PUBLIC_FIELDS = ("卖家信用等级", "卖家收到的评价总数", "作为卖家的好评数", "卖家发布的商品列表")
PRIVATE_KEYS = ("cookie", "token", "secret", "password", "phone", "address", "contact", "email",
                "authorization", "headers", "电话", "手机", "地址", "身份证", "联系")


def text(value, limit=500):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    value = str(value).strip()
    return value[:limit] if value and value.lower() not in {"nan", "n/a", "none", "-"} else None


def image_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url = urlsplit(value)
        # Real monitor responses use HTTP image-CDN URLs. Canonicalize only the
        # exact hosts already allowed by image_safety; actual fetching stays HTTPS.
        if (url.scheme == 'http' and (url.hostname or '').lower() in {'img.alicdn.com','gw.alicdn.com'}
                and url.port is None and not url.username and not url.password and not url.fragment
                and not any(ord(c)<33 for c in value)):
            value=url._replace(scheme='https').geturl()
            url=urlsplit(value)
        host = url.hostname or ""
        if (url.scheme == "https" and not url.username and not url.password
                and url.port in (None, 443)
                and any(host == d or host.endswith('.' + d) for d in ("alicdn.com", "taobaocdn.com", "goofish.com"))):
            return value
    except ValueError:
        pass
    return None


def item_fields(item, stage):
    """Retain only fields actually supplied by the existing upstream parser."""
    result = {}
    for key in SEARCH_FIELDS:
        value = item.get(key)
        if key == "商品标签":
            value = list(dict.fromkeys(v for x in value[:20] if (v := text(x, 100)))) if isinstance(value, list) else None
        else:
            value = text(value, 100)
        if value:
            result[key] = value
    # Preserve already-returned cover pixels' URL even for collection-only search cards.
    cover=image_url(item.get('商品主图链接')) or image_url(item.get('商品主图'))
    supplied=item.get('商品图片列表')
    if isinstance(supplied,list):
        urls=list(dict.fromkeys(v for x in supplied[:30] if (v:=image_url(x))))[:12]
        if urls:result['商品图片列表']=urls;cover=cover or urls[0]
    if cover:result['商品主图链接']=cover
    if stage not in {"card", "seller_enriched"}:
        return result
    for key in DETAIL_FIELDS:
        value = item.get(key)
        if key == "商品图片列表":
            value = list(dict.fromkeys(v for x in value[:30] if (v := image_url(x))))[:12] if isinstance(value, list) else None
        elif key == "商品主图链接":
            value = image_url(value)
        elif key == "商品属性":
            value = {k[:80]: v for k, x in list(value.items())[:40]
                     if isinstance(k, str) and not any(p in k.lower() for p in PRIVATE_KEYS)
                     and (v := text(x))} if isinstance(value, dict) else None
        else:
            value = text(value, 10000 if key == "商品描述" else 100)
        if value:
            result[key] = value
    return result


def seller_fields(seller, stage):
    if stage != "seller_enriched":
        return {}
    result = {}
    for key in PUBLIC_FIELDS:
        value = seller.get(key)
        if key == "卖家发布的商品列表":
            value = [{k: v for k in ("商品标题", "商品价格", "商品状态") if (v := text(row.get(k)))}
                     for row in value[:20] if isinstance(row, dict)] if isinstance(value, list) else None
            value = [row for row in value if row.get("商品标题")] if value else None
        else:
            value = text(value, 100)
        if value:
            result[key] = value
    return result


def evidence_fields(item, seller, stage):
    fields = item_fields(item, stage)
    result = {}
    # Upstream updates wantCnt from detail, with a search-card fallback. Do not
    # attribute that mixed field specifically to the search response.
    search_keys = SEARCH_FIELDS+('商品主图链接',) if stage == 'search_card' else SEARCH_FIELDS[:2]
    detail_keys = DETAIL_FIELDS + (("“想要”人数",) if stage in {'card', 'seller_enriched'} else ())
    for group, keys in (("search_card", search_keys), ("monitor_detail", detail_keys)):
        values = {k: fields[k] for k in keys if k in fields}
        if values:
            result[group] = values
    public = seller_fields(seller, stage)
    if public:
        result["seller_public"] = public
    return result


class DetailEvidenceTap:
    """Observe the existing getter's returned response, never initiate a request.

    The pinned scraper already reads data.itemDO before submitting a job. Keep
    its getter result unchanged and retain only bounded fields for that item ID.
    Unmatched/failed responses cannot contaminate another listing's evidence.
    """
    def __init__(self, *, image_audit=None):
        self.pending = OrderedDict()
        self.image_audit=image_audit

    def wrap(self, original):
        async def observed(data, *keys, **kwargs):
            result = await original(data, *keys, **kwargs)
            if keys == ('data', 'itemDO') and isinstance(data, dict) and isinstance(result, dict):
                ret = data.get('ret')
                if isinstance(ret, list) and ret and all(isinstance(r, str) and r.startswith('SUCCESS') for r in ret):
                    number = str(result.get('itemId') or '')
                    if number.isascii() and number.isdigit() and len(number) <= 50:
                        labels = result.get('itemLabelExtList')
                        attrs = {r['propertyText']: r.get('text') for r in labels[:40]
                                 if isinstance(r, dict) and isinstance(r.get('propertyText'), str)} if isinstance(labels, list) else {}
                        infos=result.get('imageInfos')
                        if self.image_audit:
                            self.image_audit.image_keys('detail_itemDO',result)
                            self.image_audit.shape('detail_imageInfos',infos)
                            for i,row in enumerate(infos[:3] if isinstance(infos,list) else []):
                                value=row.get('url') if isinstance(row,dict) else None
                                self.image_audit.url('detail_imageInfos_url',number,value,bool(image_url(value)),present=isinstance(row,dict) and 'url' in row,index=i)
                        # Use only the exact imageInfos[].url contract already read by upstream.
                        # Same-item fallback; no guessed fields or broader URL/network policy.
                        images=[r.get('url') for r in infos[:30] if isinstance(r,dict)] if isinstance(infos,list) else []
                        fields = item_fields({'商品描述': result.get('desc'), '商品属性': attrs,'商品图片列表':images}, 'card')
                        if fields:
                            self.pending[number] = fields
                            self.pending.move_to_end(number)
                            while len(self.pending) > 256:
                                self.pending.popitem(last=False)
            return result
        return observed

    def enrich(self, record):
        item = record.get('商品信息')
        if isinstance(item, dict):
            number = str(item.get('商品ID') or '')
            fields = self.pending.pop(number, {})
            item.update(fields)

def retain_search_images(original, *, image_audit=None):
    """Preserve a URL from the exact search response already parsed; no extra requests."""
    async def wrapped(data,*args,**kwargs):
        pictures={}
        payload=data.get('data') if isinstance(data,dict) else None
        rows=payload.get('resultList') if isinstance(payload,dict) else None
        if image_audit:image_audit.shape('search_rows',rows)
        for row in rows[:200] if isinstance(rows,list) else []:
            try:
                ex=row['data']['item']['main']['exContent']
                number=str(ex.get('itemId') or '')
                if image_audit:image_audit.image_keys('search_exContent',ex)
                url=image_url(ex.get('picUrl'))
                if image_audit:image_audit.url('search_picUrl',number,ex.get('picUrl'),bool(url),present='picUrl' in ex)
                if number.isascii() and number.isdigit() and url:pictures[number]=url
            except (KeyError,TypeError,AttributeError):continue
        parsed=await original(data,*args,**kwargs)
        if image_audit:image_audit.shape('search_parsed',parsed)
        for item in parsed if isinstance(parsed,list) else []:
            if isinstance(item,dict) and str(item.get('商品ID')) in pictures:
                item['商品主图链接']=pictures[str(item['商品ID'])]
            if image_audit:image_audit.output('search_output',item)
        return parsed
    return wrapped
