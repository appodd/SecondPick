"""Small evidence-based adapters shared by existing market code, not a scheduler.

All extracted fields are saved seller/page claims. Unknown is never a wildcard
for a known configuration. No authentication or subjective value score here.
"""
import re
import unicodedata


def compact(value):return re.sub(r'[\s+]+','',str(value or '')).lower()


def primary_text(card):
    title=str(card.get('title') or '')
    description=str(card.get('search_description') or card.get('description_excerpt') or '')
    text=title+('\n'+description if description and description!=title else '')
    text=re.split(r'关联[:：]|关联佳能|关键词[:：]|相关搜索',text)[0]
    # "入了pro2，出闲置两个SwitchPro" sells the latter, not the former.
    if re.match(r'入了|换了|升级了',text):
        sale=re.search(r'(?:出闲置|出售|出个|出一|出两)',text)
        if sale:text=text[sale.start():]
    return text


def sale_type(text):
    head=re.split(r'[，,。；;\n]',text)[0][:120]
    if re.match(r'^[【\[（(\s]*(?:求购|回收|专业回收|出租|租赁|维修服务|维修报价|上门维修)',head):return 'service'
    if re.search(r'打包出|打包卖|一起出|一起卖|捆绑|主机.{0,6}[+＋].{0,6}手柄|手柄.{0,6}[+＋].{0,6}主机',text):return 'bundle'
    if re.search(r'定金|订金|换购价|补差价|仅租金|预售价',head):return 'conditional_price'
    for match in re.finditer(r'保护[硬]?壳|保护盒|充电线|数据线|电源线|连接线|摇杆帽|屏幕总成|电源适配器|电脑包|内存条|键盘膜',head):
        before=head[:match.start()]
        if re.search(r'(?:送|赠|带|含|无|没|缺|不带|没有).{0,10}$',before):continue
        if re.search(r'手柄|笔记本|电脑',before) and re.match(r'.{0,3}(?:齐全|都在|都有)',head[match.end():]) and not re.search(r'单卖|配件',head):continue
        # It is the accessory being offered, not merely mentioned in the body.
        if match.start()<12 or '配件' in head or not re.search(r'手柄|笔记本|macbook|imac|电脑|一体机|手机|iphone',head,re.I) or re.search(r'(?:手柄|macbook|笔记本|电脑|switch|imac).{0,18}$',before,re.I):return 'accessory'
    return 'single'


def _specialized(card, identity_hint=None):
    text=primary_text(card);norm=compact(text)
    monitor=((card.get('monitor_evidence') or {}).get('fields') or {}).get('monitor_detail') or {}
    attrs=dict(monitor.get('商品属性') or {})
    attrs.update(card.get('market_attributes') or {})
    if card.get('detail'):attrs.update(card['detail'].get('attributes') or {})
    model_text=str(identity_hint or attrs.get('型号') or '')
    joined=compact(text+' '+model_text)
    profile=dict(category='unknown',model=None,chip=None,memory=None,storage=None,screen=None,year=None,
        region=None,edition='standard',condition='unknown',box=None,cable=None,shipping='unknown',sale_type=sale_type(text),
        issues=[],basis='saved_seller_claims_and_page_attributes',independently_verified=False)
    offered=compact(re.split(r'适配|兼容|支持|适用',text)[0])
    if re.search(r'手柄|switch|ns2|nspro',offered):
        profile['category']='controller'
        if re.search(r'(?:switch2pro|switchpro2|ns2pro|nspro2|switch2代(?:正版|原装)?pro)',offered):profile['model']='Switch 2 Pro'
        elif re.search(r'switchpro|nspro',offered):profile['model']='Switch Pro（代际非二代）'
        if re.search(r'一代',text) and not re.search(r'比一代|一代强|一代好|一代的',text):
            profile['model']='Switch Pro（一代）'
        second=r'switch2pro|switchpro2|ns2pro|nspro2|switch2代(?:正版|原装)?pro'
        def generation(value):
            if re.search(second,value):return 2
            if re.search(r'switchpro|nspro',value):return 1
        title_generation=generation(norm);attribute_generation=generation(compact(model_text))
        if title_generation and attribute_generation and title_generation!=attribute_generation:
            profile['issues'].append('型号代际声明冲突')
    family=re.search(r'mac\s*book\s*(pro|air)|i\s*mac|mac\s*(mini|studio)|thinkpad\s*([a-z]\d+)',text+' '+model_text,re.I)
    if family and profile['category']!='controller':
        text+=' '+' '.join(str(k)+': '+str(v) for k,v in attrs.items() if k in {'芯片','处理器','CPU','内存','运行内存','硬盘','存储','屏幕尺寸','年份'})
        profile['category']='computer'
        profile['model']=('MacBook '+family[1].title()) if family[1] else 'iMac' if re.search('imac',compact(family[0])) else 'Mac '+family[2].lower() if family[2] else 'ThinkPad '+family[3].upper()
        chips=set()
        for m in re.finditer(r'(?<![a-z0-9])m\s*(\d+)(?!\d)\s*(pro|max|ultra)?(?![a-z])',text,re.I):
            chips.add('M'+m[1]+(' '+m[2].lower() if m[2] else ''))
        for m in re.finditer(r'(?<![a-z0-9])i([3579])(-\d{4,5}[a-z0-9]*)?(?![a-z0-9])',text,re.I):chips.add('Intel i'+m[1]+(m[2].upper() if m[2] else ''))
        if len(chips)==1:profile['chip']=next(iter(chips))
        elif len(chips)>1:profile['issues'].append('芯片声明不唯一')
        elif re.search(r'intel|英特尔',text,re.I):profile['issues'].append('Intel具体型号缺失')
        memories=set();storage=set()
        for m in re.finditer(r'(?:内存|ram)\s*(\d{1,3})\s*(?:gb|g)?|(\d{1,3})\s*(?:gb|g)\s*(?:运行)?内存',text,re.I):memories.add((m[1] or m[2])+'GB')
        for m in re.finditer(r'(?<![\d.])(8|12|16|18|24|32|36|48|64|96)\s*(?:gb|g)(?![a-z\d])',text,re.I):
            left=text[max(0,m.start()-8):m.start()];right=text[m.end():m.end()+8]
            if not re.search(r'显卡|显存|gpu',left,re.I) and not re.match(r'\s*(?:独显|显存|显卡)',right):memories.add(m[1]+'GB')
        for m in re.finditer(r'(?<!\d)(128|256|512)\s*(?:gb|g)(?![a-z\d])|(?<![\d.])([1248])\s*(?:tb|t)(?![a-z\d])',text,re.I):storage.add(m[1]+'GB' if m[1] else m[2]+'TB')
        for m in re.finditer(r'(?<!\d)(8|16|24|32|64|96)\s*[+/]\s*(128|256|512|[1248]t(?:b)?)(?!\d)',text,re.I):
            memories.add(m[1]+'GB');storage.add(m[2]+'GB' if m[2].isdigit() else m[2].upper().replace('TB','T')+'B')
        for key,values in [('memory',memories),('storage',storage)]:
            if len(values)==1:profile[key]=next(iter(values))
            elif values:profile['issues'].append(key+'声明不唯一')
        # A displayed "1 6G内存" must never become a fabricated 6GB spec.
        # Preserve ambiguity rather than guessing how separated digits join.
        if re.search(r'(?<!\d)\d+\s+\d+\s*(?:gb|g)\s*内存',text,re.I):
            profile['memory']=None;profile['issues'].append('内存数字断行，待确认')
        sizes=set(re.findall(r'(?<!\d)(13(?:\.3)?|14(?:\.2)?|15(?:\.4)?|16(?:\.2)?|21\.5|24|27)\s*(?:寸|英寸|inch)',text,re.I))
        sizes.update(re.findall(r'imac\s*(21\.5|24|27)(?!\d)',text,re.I))
        years=set(re.findall(r'(?<!\d)(20[12]\d)(?!\d)',text))
        if len(sizes)==1:profile['screen']=next(iter(sizes))
        elif len(sizes)>1:profile['issues'].append('屏幕尺寸不唯一')
        if len(years)==1:profile['year']=next(iter(years))
    # Search cards may insert display line breaks inside Chinese words. These
    # are formatting, not evidence that a seller omitted the rest of the word.
    text=re.sub(r'\s+','',text)
    if re.search(r'限定|限量',text) or profile['category']=='controller' and '生化' in text:profile['edition']='limited'
    if re.search(r'改壳|换壳|壳子来自|贴了.*皮|dbrand',text,re.I):profile['edition']='modified_or_cosmetic_variant'
    if '日版' in text:profile['region']='日版'
    elif '港版' in text:profile['region']='港版'
    elif '国行' in text:profile['region']='国行'
    condition=str(attrs.get('成色') or '')
    opened=bool(re.search(r'仅拆|开箱验货|拆封仅|试玩|准新|几乎全新|基本全新|[89][0-9]?新|二手|自用|用过|没用几次|没怎么用|成色.{0,4}新|成色不错|保存很好|很新|有点脏|使用痕迹',text+condition))
    sealed=bool(re.search(r'未拆|原封|全新未使用',text+condition))
    if sealed and opened and not re.search(r'发货的是未拆|展示.*未拆|未拆.{0,8}仅.*外箱',text):
        profile['condition']='conflict';profile['issues'].append('未拆与已使用成色声明混杂')
    elif sealed:profile['condition']='sealed'
    elif opened:profile['condition']='opened'
    elif '全新' in text+condition:profile['condition']='new_unspecified'
    if re.search(r'无原盒|无包装|无盒|没有.*盒|无其他|无配件',text):profile['box']=False
    elif re.search(r'带.*盒|有.*盒|原包装|原装盒|箱说|包装盒.{0,10}齐全',text):profile['box']=True
    if re.search(r'无充电线|没.{0,3}线|没有数据线|无其他|无配件',text):profile['cable']=False
    elif re.search(r'带.{0,15}(?:充电线|数据线)|有盒有线|有原装线|盒.{0,5}线齐|盒和线|盒子和数据线|(?:充电线|数据线).{0,5}齐全',text):profile['cable']=True
    if re.search(r'仅同城自提|只支持.{0,8}自提|仅支持自提',text):profile['shipping']='pickup_only'
    elif '不包邮' in text or '邮费自理' in text or '邮费加' in text:profile['shipping']='extra_or_conditional'
    elif '包邮' in text:profile['shipping']='seller_claimed_shipping_included'
    # Preserve an actually saved page label, not unrelated recommendation text.
    raw=str(card.get('raw_text_excerpt') or '').split('为你推荐')[0]
    if re.search(r'(?:^|\n)包邮(?:\n|$)',raw):profile['shipping']='platform_display_shipping_included'
    if (card.get('market_page_fields') or {}).get('shipping')=='included':profile['shipping']='platform_display_shipping_included'
    if re.search(r'主页.{0,10}才有标价|主页.{0,8}才.*这个价',text):profile['issues'].append('标价附带优惠条件')
    quoted=re.search(r'普通版\s*(\d+)',text)
    if quoted and card.get('price_value') is not None and float(quoted[1])!=card['price_value']:profile['issues'].append('标题版本价与保存标价不同')
    return profile


FIELD_ALIASES = {
    'model': ('型号','产品型号','具体型号','型号代码','产品编号','model','modelnumber','modelname','modelno','mpn'),
    'identity': ('产品身份','商品身份','产品标识','产品名称','productidentity','productname','itemname'),
    'brand': ('品牌','brand','brandname'),
    'product_type': ('品类','类别','分类','商品类型','产品类型','category','type','producttype','itemtype'),
    'variant': ('版本','型号变体','变体','version','variant','edition'),
    'scope': ('售卖范围','销售范围','出售范围','出售内容','套装','套装内容','scope','bundle','salescope','sellingscope','bundlecontents'),
    'condition': ('成色','新旧程度','物品状态','condition'),
    'chip': ('芯片','处理器','cpu','processor'),
    'memory': ('内存','运行内存','ram','memory'),
    'storage': ('容量','存储','硬盘','存储容量','硬盘容量','capacity','storage'),
    'screen': ('屏幕尺寸','显示尺寸','screensize'),
    'size': ('尺寸','尺码','size'),
    'interface': ('接口','interface'),
    'material': ('材质','材料','material'),
    'quantity': ('数量','件数','quantity'),
    'year': ('年份','year'),
    'color': ('颜色','colour','color'),
}
IDENTITY_FIELDS={'model','identity','brand','product_type','variant','scope','condition'}
METADATA_FIELDS={'价格','售价','原价','浏览量','想要人数','发布时间','发货地','城市','卖家所在地','卖家地区','sku','库存号','库存编码','库存编号'}
SOFT_DIMENSIONS={'color','box','cable'}
def field_key(value):
    return re.sub(r'[\s_-]+','',unicodedata.normalize('NFKC',str(value))).casefold()


ALIASES={field_key(alias):key for key,aliases in FIELD_ALIASES.items() for alias in aliases}


def normalized(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value))).casefold()


def model_key(value):
    value=normalized(value)
    # Reuse the existing controller aliases; no brand-only model buckets.
    if re.fullmatch(r'(?:nintendo|任天堂)?(?:switch2pro|switchpro2|ns2pro|nspro2)(?:手柄|控制器)?',value):return 'switch2pro'
    return value


def value_key(key,value):
    value=normalized(value)
    if key=='model':return model_key(value)
    if key in {'memory','storage'}:
        value=re.sub(r'^(\d+(?:\.\d+)?)([gmt])$',r'\1\2b',value)
    if key=='chip':
        value=value.replace('intelcore','intel')
        value=re.sub(r'^(i[3579](?:-|$))',r'intel\1',value)
        value=re.sub(r'^(?:apple|苹果)(?=m\d)', '',value)
    return value


def _attributes(card):
    """Retain conflicting saved declarations instead of update()-overwriting.

    These sources may be the same seller. Counts are never confidence scores.
    No free-text study conclusion is promoted to a product attribute.
    """
    monitor=card.get('monitor_evidence') or {}
    fields=(monitor.get('fields') or {}).get('monitor_detail') or {}
    origin=((monitor.get('field_sources') or {}).get('monitor_detail') or {}).get('商品属性') or {}
    provenance=card.get('market_provenance') or {}
    sources=[('monitor_seller_attributes',fields.get('商品属性'),origin),
        ('saved_detail_attributes',card.get('market_attributes'),provenance),
        ('saved_detail_attributes',(card.get('detail') or {}).get('attributes'),{'detail_snapshot_id':(card.get('detail') or {}).get('snapshot_id')})]
    values={};records={};labels={};unprocessed=[]
    for source,attrs,ref in sources:
        if not isinstance(attrs,dict):continue
        ordered=sorted(attrs.items(),key=lambda pair:(ALIASES.get(field_key(pair[0])) not in IDENTITY_FIELDS,str(pair[0])))
        if len(ordered)>64:unprocessed.append('属性数量超过本地解析上限')
        for label,value in ordered[:64]:
            if not isinstance(label,str) or len(label)>80:
                unprocessed.append('存在无法解析的属性名');continue
            field=field_key(label)
            if field in METADATA_FIELDS or re.search(r'电话|微信|手机号|联系人|联系方式|住址',field):continue
            key=ALIASES.get(field,field)
            labels.setdefault(key,label)
            if value is None:continue
            if not isinstance(value,(str,int,float,bool)):
                unprocessed.append(key);continue
            text=str(value).strip()
            if len(text)>500:
                unprocessed.append(key);continue
            if not text or normalized(text) in {'未知','不详','未提供','unknown','n/a','-','nan','inf','infinity'}:continue
            values.setdefault(key,{})[value_key(key,text)]=text
            record=dict(value=text,source=source,reference=ref,independently_verified=False)
            if record not in records.setdefault(key,[]):records[key].append(record)
    single={k:next(iter(v.values())) for k,v in values.items() if len(v)==1}
    conflicts=[dict(field=k,values=list(v.values()),sources=records[k]) for k,v in values.items() if len(v)>1]
    return single,conflicts,records,labels,sorted(set(unprocessed))


def describe(card):
    attrs,conflicts,sources,labels,unprocessed=_attributes(card)
    profile=_specialized(card,attrs.get('model'))
    text=primary_text(card)
    # Explicit goods attributes define the subject. A supported device or gift
    # mentioned in the title must not let an unrelated adapter veto that subject.
    domain={'computer':r'电脑|计算机|笔记本|一体机|macbook|thinkpad|imac', 'controller':r'手柄|控制器'}
    kind=profile['category'];declared_type=attrs.get('product_type')
    owner=attrs.get('model') or attrs.get('identity')
    main_text=re.split(r'附赠|赠送|附送|另送|送一|送个|适配|兼容|支持|适用',text,maxsplit=1)[0]
    explicit_other_subject=declared_type and kind in domain and not re.search(domain[kind],declared_type,re.I)
    literal_owner=owner and normalized(owner) in normalized(main_text) and profile['model'] and model_key(owner)!=model_key(profile['model'])
    if explicit_other_subject or literal_owner:
        for key in ('model','chip','memory','storage','screen','year'):profile[key]=None
        profile['category']='unknown'
        profile['issues']=[s for s in profile['issues'] if not re.search(r'芯片|memory|storage|屏幕|内存',s)]
    adapter_model=profile['model']
    explicit=attrs.get('model') or attrs.get('identity')
    labelled=re.search(r'(?:型号|model)\s*[:：]\s*([\w.-]+)',text,re.I)
    # A concrete saved identity takes precedence over a family parser. If both
    # state different concrete controller identities, keep the conflict.
    if explicit:
        if attrs.get('model') and adapter_model and profile['category']=='controller' and model_key(explicit)!=model_key(adapter_model):
            conflicts.append(dict(field='model',values=[explicit,adapter_model],sources=['saved_attribute','title_adapter']))
        profile['model']='Switch 2 Pro' if model_key(explicit)=='switch2pro' else explicit
        if labelled and model_key(labelled[1])!=model_key(explicit):
            conflicts.append(dict(field='model',values=[explicit,labelled[1]],sources=['saved_attribute','labelled_title']))
        if adapter_model and profile['category']=='computer' and re.search(r'macbook\s*(?:pro|air)|thinkpad',explicit,re.I) and not model_key(explicit).startswith(model_key(adapter_model)):
            conflicts.append(dict(field='model',values=[explicit,adapter_model],sources=['saved_attribute','title_series']))
    elif not adapter_model:
        # Title-only opaque model codes require an explicit sale scope. This
        # also preserves the old camera "A7III 单机" use case without a camera adapter.
        codes=re.findall(r'(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9.-]*\d[A-Za-z0-9.-]*)(?![A-Za-z0-9])',text)
        codes=[c for c in codes if not re.fullmatch(r'\d*(?:GB|TB|USB\d*|NVME)',c,re.I)]
        if labelled:profile['model']=labelled[1]
        elif len(set(map(normalized,codes)))==1 and re.search(r'单机身|仅机身|单机|裸机',text):profile['model']=codes[0]
    if profile['model'] and model_key(profile['model'])=='switch2pro':profile['model']='Switch 2 Pro'
    profile.update(brand=attrs.get('brand'),product_type=attrs.get('product_type'),variant=attrs.get('variant'),
        identity_key=model_key(profile['model']) if profile['model'] else None,
        identity_source='saved_model_attribute' if attrs.get('model') else 'saved_product_identity' if attrs.get('identity') else 'specialized_title_parser' if adapter_model else 'explicit_title_model' if profile['model'] else 'missing',
        attribute_sources=sources,attribute_labels=labels,conflicts=conflicts,incomplete_attributes=unprocessed,
        limitations=['属性为卖家声明/页面展示；重复来源不是独立佐证，图片URL不是视觉核验'])
    if profile['category']=='unknown' and attrs.get('product_type'):profile['category']='generic'
    if attrs.get('condition') and profile['condition']=='unknown':
        condition=normalized(attrs['condition'])
        if re.search(r'二手|几乎全新|基本全新|[89][0-9]?新|used|preowned',condition):profile['condition']='opened'
        elif re.search(r'未拆|原封|sealed',condition):profile['condition']='sealed'
        elif condition in {'全新','new'}:profile['condition']='new_unspecified'
    scope=attrs.get('scope')
    if not scope and re.search(r'单机身|仅机身|单机|裸机',text):scope='单机'
    profile['scope']=scope
    profile['scope_basis']='saved_scope_attribute' if attrs.get('scope') else 'explicit_title_scope' if scope else 'not_separately_declared'
    profile['edition_basis']='saved_variant_attribute' if attrs.get('variant') else 'special_variant_title_claim' if profile['edition']!='standard' else 'no_special_variant_claim_found'
    role_problem=None
    if not scope and re.search(r'单卖',text):role_problem='单卖对象未明确，请补充售卖范围'
    compatibility=re.split(r'适配|适用|兼容',text,maxsplit=1)
    if explicit and len(compatibility)>1 and not adapter_model:
        prefix=unicodedata.normalize('NFKC',compatibility[0]).casefold()
        owner=re.search(r'(?<![a-z0-9])'+re.escape(unicodedata.normalize('NFKC',explicit).casefold())+r'(?![a-z0-9])',prefix)
        if not owner:role_problem='型号可能是适用对象，出售标的待确认'
    profile['role_problem']=role_problem
    if scope and re.search(r'仅配件|配件单卖|^配件$|^accessory$|^parts$',scope,re.I):profile['sale_type']='accessory'
    # Two explicitly identical bundles may be compared; unknown bundles never
    # masquerade as the ordinary single-item offer.
    if scope and re.search(r'套装|[+＋]|含.{1,20}',scope):profile['sale_type']='bundle'
    specs={k:v for k,v in attrs.items() if k not in IDENTITY_FIELDS}
    for key in ('chip','memory','storage','screen','year'):
        value=profile[key]
        if key in attrs:
            if value and value_key(key,value)!=value_key(key,attrs[key]):
                # A broad Intel family and its explicitly supplied SKU are
                # different specificity, not contradictory CPUs.
                if not (key=='chip' and normalized(attrs[key]).startswith(normalized(value))):
                    conflicts.append(dict(field=key,values=[attrs[key],value],sources=['saved_attribute','title_adapter']))
            profile[key]=attrs[key]
        elif value:specs[key]=value
    for c in conflicts:
        specs.pop(c['field'],None)
        if c['field'] in {'model','brand','product_type','variant','scope','chip','memory','storage','screen','year'}:profile[c['field']]=None
        if c['field']=='condition':profile['condition']='conflict'
    if any(c['field']=='model' for c in conflicts):profile['identity_key']=None
    for key in ('box','cable'):
        if profile[key] is not None:specs[key]='有' if profile[key] else '无'
    # These hints constrain only the strict layer. Missing laptop specs never
    # discard all other known attributes or prohibit broad comparison.
    expected=[]
    if adapter_model and profile['category']=='computer':
        expected=['chip','memory','storage']
        if adapter_model.startswith(('MacBook','ThinkPad')) or adapter_model=='iMac':expected.append('screen')
    if profile['identity_key']=='switch2pro':expected+=['box','cable']
    profile['specs']=specs
    profile['expected_dimensions']=expected
    profile['comparison_dimensions']=sorted(set(expected)|set(specs))
    profile['decisive_dimensions']=sorted((set(expected)|set(specs))-SOFT_DIMENSIONS)
    profile['unclassified_dimensions']=[]
    if profile['identity_source']=='saved_product_identity':profile['limitations'].append('描述性商品身份不是标准同款型号，仅作宽泛参考')
    return profile


def comparison_plan(profiles,goal):
    """Discover project dimensions from actual properties, not a product catalogue.

    Shared/variable fields and explicit goal field names are comparison axes,
    not newly invented shopping requirements. Single-sided unknown-significance
    fields remain visible as limitations. No AI call or free-text fact inference.
    """
    from collections import Counter
    buckets={}
    for p in profiles.values():
        if p['identity_key']:buckets.setdefault(p['identity_key'],[]).append(p)
    plans={}
    for identity,items in buckets.items():
        counts=Counter(k for p in items for k in set(p['specs'])|(set(p['attribute_labels'])-IDENTITY_FIELDS))
        expected={k for p in items for k in p['expected_dimensions']}
        def mentioned(label):
            text=normalized(goal);word=normalized(label)
            if len(word)<2 or word not in text:return False
            if re.search(r'(?:忽略|不关注|不考虑|无需|不用|不限)[^，。;；]{0,6}'+re.escape(word),text):return False
            if re.search(re.escape(word)+r'[^，。;；]{0,6}(?:无所谓|不重要|不限|不作要求)',text):return False
            return True
        focus={k for p in items for k,label in p['attribute_labels'].items() if k not in IDENTITY_FIELDS and mentioned(label)}
        # Recognizable property roles may be significant even if only one
        # side provides them. No category-specific required configuration.
        roles={'chip','memory','storage','screen','size','interface','year','material','quantity'}
        # Version/specification fields remain separate axes (e.g. generation
        # and regional version), rather than overwriting one another.
        variant_fields={k for k in counts if re.search(r'版本|变体|规格|version|variant|generation',k,re.I)}
        dimensions=sorted(expected|focus|variant_fields|{k for k,n in counts.items() if n>=2 or k in roles})
        measured={k for p in items for k,v in p['specs'].items() if re.fullmatch(r'\d+(?:\.\d+)?(?:mm|cm|m|kg|g|ml|l|w|v|a|hz|gb|tb|毫米|厘米|米|千克|克|毫升|升)',normalized(v))}
        decisive=sorted(((expected|focus|roles|measured|variant_fields)&set(dimensions))-SOFT_DIMENSIONS)
        plans[identity]=dict(dimensions=dimensions,decisive_dimensions=decisive,goal_focus=sorted(focus),basis='saved_attributes_and_explicit_goal_field_names',not_user_hard_conditions=True)
        for p in items:
            p['comparison_dimensions']=dimensions
            p['decisive_dimensions']=decisive
            p['unclassified_dimensions']=sorted(set(p['specs'])-set(dimensions))
    return plans


def match_key(profile):
    """Only matching dependencies, for a bounded per-calculation memo table."""
    return (exclusion(profile),*(normalized(profile.get(k) or '') for k in
        ('identity_key','brand','product_type','variant','scope','sale_type','edition','condition','shipping','region','identity_source')),
        tuple(profile['comparison_dimensions']),tuple(profile['decisive_dimensions']),tuple(profile['incomplete_attributes']),tuple(sorted((k,value_key(k,v)) for k,v in profile['specs'].items())))


def exclusion(profile,quote=None):
    if quote and not quote.get('valid'):return quote.get('reason') or '无明确当前售价'
    if profile.get('conflicts'):return '属性声明冲突：'+'、'.join(sorted({c['field'] for c in profile['conflicts']}))
    if profile.get('role_problem'):return profile['role_problem']
    if profile['sale_type']!='single' and not (profile['sale_type']=='bundle' and profile.get('scope')):return {'accessory':'配件单卖','service':'服务或求购','bundle':'捆绑或打包价口径不明','conditional_price':'定金、换购或其他非直接售价'}[profile['sale_type']]
    if not profile['model']:return '所售型号未明确'
    if profile['identity_key'] in {'其他','通用','无','pro','普通版','标准款','正品','原装'} or any(profile.get(k) and normalized(profile[k])==profile['identity_key'] for k in ('brand','product_type')):return '只有品牌或类别，缺少具体商品身份'
    if profile['edition']!='standard' and not profile.get('variant'):return '限定或外观改装版本，单独比较'
    if profile['condition']=='conflict':return '新旧状态声明冲突'
    fatal=[i for i in profile['issues'] if '缺失' not in i and '断行' not in i]
    if fatal:return '；'.join(fatal)
    return None


def peer_reason(target,peer,strict=False):
    reason=exclusion(peer)
    if reason:return reason
    if target['identity_key']!=peer['identity_key']:return '所售型号或代际不同'
    for key in ('brand','product_type','variant','scope'):
        if target.get(key) and peer.get(key) and normalized(target[key])!=normalized(peer[key]):return key+'明确不同'
    if bool(target.get('scope'))!=bool(peer.get('scope')):return '售卖范围仅单方明确，无法确认同一交易标的'
    if target['sale_type']!=peer['sale_type']:return '售卖标的或套装范围不同'
    if target['edition']!=peer['edition'] and not (target.get('variant') and peer.get('variant') and normalized(target['variant'])==normalized(peer['variant'])):return '版本或改装状态不同'
    if target['condition']!='unknown' and peer['condition']!='unknown' and target['condition']!=peer['condition']:return '新旧状态不同'
    if target['shipping']=='pickup_only' and peer['shipping']!='pickup_only' or peer['shipping']=='pickup_only' and target['shipping']!='pickup_only':return '仅自提与邮寄条件不同'
    if target['shipping'].endswith('shipping_included') and peer['shipping']=='extra_or_conditional':return '已知运费条件不同'
    keys=set(target['comparison_dimensions'])|set(peer['comparison_dimensions'])
    for key in sorted(keys):
        left=target['specs'].get(key);right=peer['specs'].get(key)
        if left is not None and right is not None and value_key(key,left)!=value_key(key,right):
            lv=value_key(key,left);rv=value_key(key,right)
            if key=='chip' and (re.fullmatch(r'inteli[3579]',lv) and rv.startswith(lv) or re.fullmatch(r'inteli[3579]',rv) and lv.startswith(rv)):
                if strict:return '芯片SKU未明确，仅宽泛参考'
            elif strict or key in target['decisive_dimensions'] or key in peer['decisive_dimensions']:return key+'配置不同'
        elif strict and (left is None or right is None):return key+'配置缺失，仅宽泛参考'
    if target['region'] and peer['region'] and target['region']!=peer['region']:return '已知地区版本不同'
    if strict:
        if target['incomplete_attributes'] or peer['incomplete_attributes']:return '部分保存属性尚不能完整解析，仅宽泛参考'
        if target['identity_source']=='saved_product_identity' or peer['identity_source']=='saved_product_identity':return '只有描述性商品身份，仅宽泛参考'
        if target['condition']=='unknown' or peer['condition']=='unknown':return '新旧状态未明确'
        for key in ('brand','variant','scope'):
            if bool(target.get(key))!=bool(peer.get(key)) and target['identity_source']!='specialized_title_parser' and peer['identity_source']!='specialized_title_parser':return key+'仅单方明确，仅宽泛参考'
        if target['shipping']!='unknown' and peer['shipping']!='unknown' and (target['shipping']=='extra_or_conditional')!=(peer['shipping']=='extra_or_conditional'):return '运费口径不同'
    return None
