"""Offline P3 contracts: quotes, cohorts and frozen shared research input."""
import json
from decimal import Decimal

import pytest

from shopping_agent.asking_prices import asking_amount, select_quote, apply_quote
from shopping_agent.market_comparability import describe, exclusion, peer_reason
from shopping_agent.market_baseline import project_market, bounded_reference, spec_key
from shopping_agent.project_research import ProjectResearch
from shopping_agent.db import connect, add_listing_snapshot
from test_project_research import research, ingest


def offer(price, time='2026-10-24T10:00:00+00:00', **kw):
    return dict(price_text=price,observed_at=time,recorded_at=time,kind='snapshot',record_id=1,**kw)


@pytest.mark.parametrize('value,expected',[('¥328',Decimal(328)),('338.60',Decimal('338.60')),('1.25万',Decimal(12500)),
    ('原价500现价328',None),('定金100',None),('300-400',None),('0',None),('-10',None),('NaN',None),('300起',None),('3,28',None),('3,280.50',Decimal('3280.50'))])
def test_single_asking_amount(value,expected):
    assert asking_amount(value)==expected


def test_recency_before_source_priority_and_preserve_precision():
    old=offer('338','2026-10-23T12:00:00Z');old['kind']='detail'
    latest=offer('328.60');latest['kind']='price_observation'
    q=select_quote([old,latest]);assert q['amount']=='328.60'
    assert apply_quote(dict(price_text='338'),q)['price_value']==328.6
    assert old['price_text']=='338'


def test_equal_time_conflict_latest_ambiguous_and_missing_clocks():
    assert select_quote([offer('328'),offer('338')])['status']=='conflict'
    assert select_quote([offer('338','2026-10-23'),offer('100定金')])['status']=='unknown_time'
    assert select_quote([offer('338','2026-10-23T00:00:00Z'),offer('100定金')])['status']=='ambiguous'
    assert select_quote([offer('328',None)])['status']=='unknown_time'
    q=select_quote([dict(offer('328',None),recorded_at='2026-10-24T00:00:00Z')])
    assert q['valid'] and q['time_basis']=='recorded_time_fallback' and q['warnings']
    assert select_quote([offer('328'),offer('328')])['valid']


def test_mixed_clocks_use_explicit_recorded_time_not_assumed_timezone():
    a=offer('338','2026-10-24T10:00:00');b=offer('328','2026-10-24T03:00:00Z')
    a['recorded_at']='2026-10-24T02:00:00Z';b['recorded_at']='2026-10-24T03:00:00Z'
    q=select_quote([a,b]);assert q['amount']=='328' and q['time_basis']=='recorded_time_fallback'


def card(i,title='NS2 Pro手柄 几乎全新 带原装盒子和数据线 包邮',price=328):
    return dict(listing_id=i,title=title,price_text=str(price),price_value=price,current_quote=select_quote([offer(str(price))]))


@pytest.mark.parametrize('title,expected',[
    ('Switch 2 Pro手柄 送保护壳 几乎全新','single'),('Switch2 Pro保护壳单卖','accessory'),
    ('Switch 2 Pro手柄 数据线齐全','single'),('NS2 Pro手柄 无盒送保护壳','single'),
    ('NS2 Pro手柄 总共7个打包出','bundle'),('NS2 Pro手柄 定金100','conditional_price'),
    ('MacBook Pro 电源线 配件','accessory')])
def test_sale_type_without_blanket_accessory_keyword(title,expected):
    assert describe(card(1,title))['sale_type']==expected


@pytest.mark.parametrize('title,model',[
    ('NS2 Pro手柄','Switch 2 Pro'),('Nintendo Switch+2+Pro手柄','Switch 2 Pro'),
    ('switchPro2代 几乎全新','Switch 2 Pro'),('Switch Pro一代 适配NS2主机','Switch Pro（一代）'),
    ('易速马X20 Pro适配Switch2',None)])
def test_controller_generation(title,model):
    assert describe(card(1,title))['model']==model


def test_limited_modified_bundle_and_unknown_not_generic_baseline():
    target=describe(card(1))
    for title in ['NS2 Pro手柄 生化限定 几乎全新','NS2 Pro手柄 贴了dbrand皮肤 几乎全新','NS2 Pro手柄 打包出','不明型号控制器']:
        assert peer_reason(target,describe(card(2,title)))
    assert describe(card(2,'NS2 Pro手柄 几乎全新 未拆封'))['condition']=='conflict'
    assert '冲突' in exclusion(describe(dict(card(3,'Switch Pro一代手柄 几乎全新'),market_attributes={'型号':'Switch 2 Pro'})))


def test_mac_chips_separate_unknown_not_wildcard_and_properties_respected():
    profiles=[describe(card(i,f'MacBook Pro 13寸 {chip}芯片 16GB 512GB 几乎全新',5000)) for i,chip in enumerate(['Intel i7','M1','M2'],1)]
    assert [p['chip'] for p in profiles]==['Intel i7','M1','M2']
    assert len({spec_key(p) for p in profiles})==3
    assert peer_reason(profiles[0],profiles[1])=='chip配置不同'
    partial=describe(card(4,'MacBook Pro 13寸 16GB 512GB'))
    assert peer_reason(profiles[1],partial) is None
    assert peer_reason(profiles[1],partial,strict=True).startswith('chip配置缺失')
    p=describe(dict(card(6,'MacBook Pro 13寸'),market_attributes={'芯片':'M2','内存':'16GB','硬盘':'512GB'}))
    assert p['chip']=='M2' and p['memory']=='16GB'
    assert describe(card(7,'MacBook Pro M1 M2 16GB 512GB'))['chip'] is None
    assert describe(card(8,'MacBook Pro Intel i9 1 6G内存 1TB 16寸'))['memory'] is None


def test_layer_partition_self_exclusion_decimal_and_small_sample_limits():
    rows=[card(1),card(2,price=318.6),card(3,price=330),card(4,'NS2 Pro手柄 几乎全新 无盒无配件',310),
          card(5,'NS2 Pro手柄 全新未拆封',360),card(6,'NS2 Pro手柄 生化限定 几乎全新',410)]
    market=project_market(rows+rows,'NS2 Pro','2026-10-24');r=market['references']['1']
    assert market['scope_count']==6 and r['broad']['member_ids']==[2,3,4]
    assert r['strict']['member_ids']==[2,3] and r['strict']['summary']['median']==324.3
    assert r['excluded_count']+r['broad']['count']==r['peer_total']==5
    assert '样本不足' in r['strict']['position'] and 'percentile' not in r
    assert r['samples'][0]['quote']['record_id']==1
    assert 'excluded' not in bounded_reference(r)
    assert len(bounded_reference(r)['samples'])<=4


def test_no_comparison_without_known_configuration_or_current_quote():
    a=card(1,'未知型号商品');b=card(2,'未知型号商品')
    m=project_market([a,b],'不明品类','now');assert not m['groups'] and not m['references']['1']['broad']['count']
    a=card(1);a['current_quote']=select_quote([offer('328'),offer('338')])
    assert not project_market([a,card(2)],'NS2','now')['references']['1']['broad']['count']


def test_derived_market_never_changes_own_research_signature():
    a=card(1);b=dict(a,current_quote=dict(a['current_quote'],observed_at='later'),price_history=[{'price':328}],market_attributes={'型号':'NS2'},local_market_reference={'median':999})
    assert ProjectResearch.signature(a)==ProjectResearch.signature(b)
    assert ProjectResearch.signature(a)!=ProjectResearch.signature(dict(a,price_text='329',price_value=329))
    assert ProjectResearch.signature(a)!=ProjectResearch.signature(dict(a,current_quote=select_quote([offer('100定金')])))


@pytest.mark.parametrize('path',['首轮','增量','有限补研','目标校准','新证据复评'])
def test_all_paths_share_bounded_frozen_market_without_expanding_scope(research,path):
    p=research;task=p.task_id
    ids=[ingest(p,title='NS2 Pro手柄 几乎全新 带原装盒子和数据线 包邮',price=str(price)) for price in (328,318,330)]
    cards=p.cards(task)
    request=p._request(task,[cards[0]],path)
    assert request.allowed_listing_ids=={ids[0]}
    ref=json.loads(request.evidence[0].data['evidence_json'])['local_market_reference']
    assert ref['goal_revision']==1 and ref['broad']['count']==2 and ids[0] not in ref['broad']['member_ids']
    assert set(ref['broad']['member_ids'])==set(ids[1:])
    assert '挂牌价格竞争力' in request.messages[0].content and '不是成交价' in request.messages[0].content
    assert '整组属性表述必须有覆盖全部成员的依据' in request.messages[0].content
    assert 'UNKNOWN必须保留为未知' in request.messages[0].content
    frozen=request.model_dump_json()
    # A later quote updates a newly computed baseline, never a frozen request.
    with connect(p.config.database_path) as conn:
        run=cards[1]['source_run_ids'][0]
        add_listing_snapshot(conn,ids[1],run,title=cards[1]['title'],price_text='400')
    assert request.model_dump_json()==frozen
    assert p.signature(cards[0])==p.signature(next(c for c in p.cards(task) if c['listing_id']==ids[0]))
    assert p._request(task,[cards[0]],path).model_dump_json()!=frozen
    assert not p.runtime.requests
    p.control(task,'pause');v=p.overview(task)
    assert v['policy']['paused']==1 and not p.execute_next() and not p.runtime.requests
