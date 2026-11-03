"""Actual generality acceptance, not the earlier characterization assertions.

All examples are constructed saved-attribute records. No real AI or collection.
"""
import copy
import json
import random

import pytest

from shopping_agent.asking_prices import apply_quote,select_quote
from shopping_agent.market_baseline import project_market,bounded_reference
from shopping_agent.market_comparability import describe,exclusion,peer_reason
from shopping_agent.db import add_detail_snapshot
from test_project_research import research,ingest


def saved(i,attrs,*,title='保存商品，自用',price=100):
    row=dict(listing_id=i,title=title,price_text=str(price),price_value=price,market_attributes=attrs,
        market_provenance={'listing_snapshot_id':i,'detail_snapshot_id':i})
    return apply_quote(row,select_quote([dict(kind='snapshot',record_id=i,run_id=1,price_text=str(price),
        observed_at='2026-10-24T00:00:00Z',recorded_at='2026-10-24T00:00:00Z')]))


def market(rows,goal='选择已保存的商品',time='2026-10-24T00:00:00Z'):
    return project_market(rows,goal,time)


CASES=[
    dict(品类='相机',品牌='Sony',型号='A7III',售卖范围='单机身',成色='二手'),
    dict(品类='固态硬盘',品牌='WD',型号='SN850X',容量='2TB',接口='NVMe',成色='二手'),
    dict(品类='办公椅',品牌='澄木',型号='ErgoFlex A',尺码='B',材质='网布',成色='二手'),
    # Never supported by an adapter: opaque identity and arbitrary property names.
    dict(品类='实验夹具',品牌='LumoLab',型号='Rail-Q7',导轨行程='320mm',夹持开口='45mm',成色='二手'),
]


@pytest.mark.parametrize('attrs',CASES)
def test_unadapted_explicit_identity_forms_traceable_comparable_layers(attrs):
    rows=[saved(1,attrs,price=100.5),saved(2,dict(attrs),price=120),saved(3,dict(attrs,型号='DIFFERENT-9'),price=30)]
    result=market(rows);ref=result['references']['1']
    assert result['profiles']['1']['category']=='generic'
    assert ref['broad']['member_ids']==ref['strict']['member_ids']==[2]
    assert ref['broad']['summary']['median']==120
    assert ref['exclusion_counts']=={'所售型号或代际不同':1}
    assert ref['samples'][0]['profile_source']['detail_snapshot_id']==2
    assert all(not source['independently_verified'] for sources in result['profiles']['1']['attribute_sources'].values() for source in sources)


def test_unrelated_adapter_mentions_cannot_veto_explicit_generic_subject():
    for title in ('Rail-Q7 实验夹具，适配 MacBook Pro M2','Rail-Q7 实验夹具，附赠 NS2 Pro手柄'):
        result=market([saved(1,CASES[3],title=title),saved(2,CASES[3])])
        assert result['profiles']['1']['category']=='generic'
        assert result['references']['1']['strict']['member_ids']==[2]
    attrs={'品类':'实验仪器','品牌':'Lab','型号':'BX-7','成色':'二手'}
    assert not exclusion(describe(saved(1,attrs,title='BX-7 生化分析仪 自用')))


def test_same_explicit_variant_does_not_require_identical_title_keywords():
    attrs=dict(CASES[3],版本='Collector V3')
    result=market([saved(1,attrs,title='Rail-Q7 限量版自用'),saved(2,attrs)])
    assert result['references']['1']['strict']['member_ids']==[2]


def test_model_not_brand_or_category_is_identity():
    for attrs in [dict(品牌='Sony',品类='相机'),dict(品牌='澄木',品类='办公椅'),dict(型号='办公椅',品类='办公椅'),dict(SKU='001',品类='办公椅')]:
        ref=market([saved(1,attrs),saved(2,attrs)])['references']['1']
        assert not ref['broad']['count'] and ref['unavailable_reason']
    attrs=dict(品牌='飞智',品类='游戏手柄',型号='黑武士5Pro',成色='二手')
    ref=market([saved(1,attrs),saved(2,dict(attrs,型号='八爪鱼4Pro'))])['references']['1']
    assert not ref['broad']['count'] and ref['excluded'][0]['reason']=='所售型号或代际不同'


def test_generic_field_names_normalize_without_changing_opaque_model_values():
    a={'Brand Name':'Maker','Model Number':'X-8','Condition':'used','Jaw_Width':'45mm'}
    b={'brand':'Maker','model':'X-8','condition':'used','jaw width':'45 mm'}
    r=market([saved(1,a),saved(2,b)])['references']['1']
    assert r['strict']['member_ids']==[2]
    bad=dict(b,model='X8')
    assert not market([saved(1,a),saved(2,bad)])['references']['1']['broad']['count']


def test_group_navigation_keys_cannot_collide_through_attribute_separators():
    a=dict(CASES[3],品牌='a|scope:b')
    b=dict(CASES[3],品牌='a',售卖范围='b')
    groups=market([saved(1,a),saved(2,b)])['groups']
    assert len(groups)==2 and len({g['key'] for g in groups})==2


def test_explicit_descriptive_product_identity_without_model_is_only_broad():
    attrs={'品类':'手工灯具','产品身份':'白橡木弯曲灯座款','材质':'白橡木','成色':'二手','高度':'320mm'}
    result=market([saved(1,attrs),saved(2,attrs)])
    ref=result['references']['1']
    assert ref['broad']['member_ids']==[2] and not ref['strict']['count']
    assert result['profiles']['1']['identity_source']=='saved_product_identity'
    assert any('非标准同款型号' in s for s in ref['limitations'])


def test_scope_and_bundles_are_not_silently_mixed():
    attrs=CASES[0]
    rows=[saved(1,attrs),saved(2,dict(attrs,售卖范围='机身+镜头')),saved(3,dict(attrs,售卖范围='仅配件'))]
    result=market(rows)
    assert not result['references']['1']['broad']['count']
    assert 'scope明确不同' in result['references']['1']['exclusion_counts']
    assert '配件单卖' in result['references']['1']['exclusion_counts']
    bundled=market([rows[1],saved(4,dict(attrs,售卖范围='机身+镜头'))])
    assert bundled['references']['2']['strict']['member_ids']==[4]


def test_compatibility_model_and_unspecified_standalone_item_are_not_owner_identity():
    attrs={'型号':'A7III','品牌':'Sony','成色':'二手'}
    for title in ('Sony A7III 电池单卖','电池，适配 Sony A7III'):
        p=describe(saved(1,attrs,title=title))
        assert '待确认' in exclusion(p) or '未明确' in exclusion(p)
    rows=[saved(1,CASES[0]),saved(2,attrs)]
    ref=market(rows)['references']['1']
    assert not ref['broad']['count'] and '售卖范围仅单方明确' in ref['excluded'][0]['reason']


@pytest.mark.parametrize('attrs,key,value',[(CASES[1],'容量','1TB'),(CASES[2],'尺码','C'),(CASES[3],'夹持开口','70mm')])
def test_known_price_relevant_differences_not_same_strict_or_broad_baseline(attrs,key,value):
    ref=market([saved(1,attrs),saved(2,dict(attrs,**{key:value}))])['references']['1']
    assert not ref['strict']['count'] and not ref['broad']['count']
    assert any('配置不同' in r['reason'] for r in ref['excluded'])


def test_partial_spec_unknown_broad_not_strict_and_does_not_erase_known_values():
    attrs=CASES[1];partial={k:v for k,v in attrs.items() if k!='容量'}
    result=market([saved(1,attrs),saved(2,partial)])
    r=result['references']['1']
    assert r['broad']['member_ids']==[2] and not r['strict']['count']
    assert r['strict_excluded'][0]['reason'].startswith('storage配置缺失')
    assert result['profiles']['2']['specs']['interface']=='NVMe'
    assert any('属性缺失' in s for s in r['limitations'])


def test_project_goal_can_focus_arbitrary_saved_field_without_creating_a_hard_condition():
    attrs=dict(CASES[3],噪声声明='低')
    rows=[saved(1,attrs),saved(2,CASES[3])]
    a=market(rows);b=market(rows,'关注噪声声明')
    assert '噪声声明' not in a['references']['1']['comparison_dimensions']
    assert '噪声声明' in b['references']['1']['comparison_dimensions']
    assert b['references']['1']['comparison_plan']['not_user_hard_conditions']
    assert b['references']['1']['broad']['member_ids']==[2]
    assert not b['references']['1']['strict']['count']
    for goal in ('忽略噪声声明','噪声声明无所谓'):
        assert '噪声声明' not in market(rows,goal)['references']['1']['comparison_dimensions']


def test_independent_version_axes_never_overwrite_and_shipping_city_is_not_a_preference():
    attrs=dict(CASES[3],版本='V2',地区版本='JP',发货地='上海')
    other=dict(attrs,地区版本='CN',发货地='北京')
    p=describe(saved(1,attrs));assert not p['conflicts'] and '发货地' not in p['specs']
    assert not market([saved(1,attrs),saved(2,other)])['references']['1']['broad']['count']
    other['地区版本']='JP'
    assert market([saved(1,attrs),saved(2,other)])['references']['1']['strict']['member_ids']==[2]


def test_uncertain_categorical_property_difference_is_explicitly_only_broad():
    rows=[saved(1,dict(CASES[3],表面处理='A工艺')),saved(2,dict(CASES[3],表面处理='B工艺'))]
    ref=market(rows)['references']['1']
    assert ref['broad']['member_ids']==[2] and not ref['strict']['count']
    assert ref['broad_differences']==[{'listing_id':2,'fields':['表面处理']}]
    assert any('非决定性属性差异' in s for s in ref['limitations'])
    focused=market(rows,'关注表面处理')['references']['1']
    assert not focused['broad']['count']


def test_all_sources_and_aliases_keep_real_conflicts_and_never_count_as_independent_proof():
    row=saved(1,dict(CASES[1],容量='2 TB'))
    row['monitor_evidence']=dict(fields={'monitor_detail':{'商品属性':{'capacity':'1TB','model':'SN850X'}}},
        field_sources={'monitor_detail':{'商品属性':{'snapshot_id':19,'observed_at':'2026-10-23'}}})
    p=describe(row)
    assert p['conflicts'][0]['field']=='storage'
    assert 'storage' not in p['specs'] and len(p['attribute_sources']['storage'])==2
    assert '冲突' in exclusion(p)
    row['monitor_evidence']['fields']['monitor_detail']['商品属性']['capacity']='2tb'
    p=describe(row);assert not p['conflicts'] and len(p['attribute_sources']['storage'])==2
    assert all(not s['independently_verified'] for s in p['attribute_sources']['storage'])
    assert 'confidence' not in p


def test_generic_labelled_title_conflict_does_not_get_overwritten_by_attributes():
    row=saved(1,CASES[1],title='型号: SN770，自用')
    assert '冲突' in exclusion(describe(row))


def test_unknown_property_roles_never_extract_authority_from_old_free_text_studies():
    row=saved(1,{'品类':'办公椅'})
    row['assessment']={'model':'Imaginary-7','summary':'AI guesses this is model X'}
    row['comparison_group']='Imaginary-7'
    p=describe(row);assert not p['model'] and exclusion(p)=='所售型号未明确'


@pytest.mark.parametrize('chip',['M9','M27 Pro','NovaCore X90'])
def test_new_chip_identity_is_open_and_explicit_unknown_vendor_is_usable(chip):
    attrs={'型号':'MacBook Pro','CPU':chip,'内存':'16GB','存储':'512GB','屏幕尺寸':'14','成色':'二手'}
    result=market([saved(1,attrs),saved(2,attrs)])
    assert result['references']['1']['strict']['member_ids']==[2]
    assert result['profiles']['1']['specs']['chip']==chip


def test_distinct_intel_skus_do_not_collapse_and_known_family_is_only_broad():
    attrs={'型号':'ThinkPad X1 Carbon','CPU':'i7-8550U','内存':'16GB','存储':'512GB','屏幕尺寸':'14','成色':'二手'}
    rows=[saved(1,attrs),saved(2,dict(attrs,CPU='i7-10510U')),saved(3,dict(attrs,CPU='Intel i7'))]
    result=market(rows)
    assert result['references']['1']['broad']['member_ids']==[3]
    assert not result['references']['1']['strict']['count']
    title='ThinkPad X1 Carbon Intel i7-8550U 16GB 512GB 14寸 自用'
    p=describe(saved(4,attrs,title=title));assert not p['conflicts'] and p['chip']=='i7-8550U'


def test_unrecognized_chip_no_longer_prohibits_broad_comparison():
    a=saved(1,{},title='MacBook Pro 13寸 16GB 512GB 几乎全新')
    b=saved(2,{},title='MacBook Pro M9 13寸 16GB 512GB 几乎全新')
    ref=market([a,b])['references']['1']
    assert ref['broad']['member_ids']==[2] and not ref['strict']['count']


def test_unknown_condition_is_only_broad_and_does_not_fake_complete_equivalence():
    attrs={k:v for k,v in CASES[0].items() if k!='成色'}
    result=market([saved(1,attrs,title='保存商品'),saved(2,attrs,title='保存商品')])
    ref=result['references']['1']
    assert ref['broad']['count']==1 and not ref['strict']['count']
    assert any('严格仅表示' in s for s in ref['limitations'])


def test_title_only_old_camera_scope_uses_shared_backend_not_silent_legacy_statistics():
    rows=[saved(1,{},title='Sony A7III 单机 自用'),saved(2,{},title='Sony A7III 单机 自用'),saved(3,{},title='Sony A7IV 单机 自用')]
    result=market(rows)
    assert result['comparison_version']==2
    assert result['references']['1']['broad']['member_ids']==[2]
    assert result['profiles']['1']['identity_source']=='explicit_title_model'
    assert result['groups']


def test_price_source_precision_self_exclusion_and_determinism_with_bounded_memo():
    rows=[saved(i,CASES[3],price=100+i/10) for i in range(1,41)]
    original=copy.deepcopy(rows)
    a=market(rows+rows[:1]);random.Random(7).shuffle(rows);b=market(rows)
    assert a==b and original==sorted(rows,key=lambda c:c['listing_id'])
    r=a['references']['1'];assert r['broad']['count']==39 and 1 not in r['broad']['member_ids']
    assert len(bounded_reference(r)['samples'])<=4
    c=market(rows,time='2026-10-25');assert c['references']['1']['data_digest']==r['data_digest']
    rows[0]['market_attributes']=dict(CASES[3],导轨行程='999mm')
    d=market(rows);assert d['references']['1']['data_digest']!=r['data_digest']


def test_peer_excerpt_is_bounded_without_truncating_full_comparison_facts():
    attrs=dict(CASES[3],**{f'特性{i}':'x'*170+str(i) for i in range(20)})
    r=market([saved(1,attrs),saved(2,attrs)])['references']['1']
    excerpt=bounded_reference(r)
    p=excerpt['samples'][0]['profile']
    assert len(p['specs'])<=12 and len(p['omitted_peer_attributes'])==20
    assert len(r['samples'][0]['profile']['specs'])>12  # Original projection intact.
    assert r['strict']['member_ids']==[2]


def test_declared_unknown_configuration_is_not_silently_treated_as_equal():
    attrs=dict(CASES[1],容量=None)
    r=market([saved(1,attrs),saved(2,attrs)])['references']['1']
    assert r['broad']['member_ids']==[2] and not r['strict']['count']
    assert 'storage' in r['comparison_dimensions']


def test_unprocessed_properties_keep_identity_but_downgrade_strict_claim():
    attrs=dict(CASES[3],接口说明={'mode':'unknown'})
    result=market([saved(1,attrs),saved(2,attrs)])
    assert result['references']['1']['broad']['member_ids']==[2]
    assert not result['references']['1']['strict']['count']
    assert result['profiles']['1']['incomplete_attributes']==['接口说明']
    huge=dict(CASES[3],**{f'extra{i}':'x' for i in range(80)})
    p=describe(saved(1,huge));assert p['model']=='Rail-Q7' and p['incomplete_attributes']


def test_shared_request_reads_actual_saved_properties_with_no_extra_run(research):
    p=research;task=p.task_id;p.control(task,'pause')
    ids=[ingest(p,title='构造实验夹具 自用',price=str(price)) for price in (100,120)]
    with p.source_db() as conn:
        for listing in ids:
            row=conn.execute('SELECT * FROM listing_snapshots WHERE listing_id=?',(listing,)).fetchone()
            path=p.config.database_path.parent/'not-retained.txt'
            add_detail_snapshot(conn,listing,row['run_id'],'https://www.goofish.com/item?id='+str(listing),'saved',
                path,path,path,path,path,0,0,False,attributes_json=json.dumps(CASES[3]),attributes_source='saved_seller_attribute')
    cards=p.cards(task);request=p._request(task,cards[:1],'对已保存商品作研究')
    assert request.allowed_listing_ids=={ids[0]}
    ref=json.loads(request.evidence[0].data['evidence_json'])['local_market_reference']
    assert ref['broad']['member_ids']==ref['strict']['member_ids']==[ids[1]]
    assert '导轨行程' in ref['comparison_dimensions'] and '夹持开口' in ref['comparison_dimensions']
    assert not p.execute_next() and not p.runtime.requests and p.policy(task)['paused']==1
    with p.db() as conn:assert conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0]==0
