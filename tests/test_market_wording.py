"""P3 wording contract only: saved evidence and Mock input, no real reasoning."""
import ast
import copy
import json
from pathlib import Path

import pytest

from shopping_agent.market_baseline import MARKET_GUIDANCE,bounded_reference,project_market
from test_market_generality import CASES,saved

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'data/artifacts/p3-wording-closeout-20261025'


@pytest.mark.skipif(not (ART/'market_baseline-before.py').is_file(), reason='Private historical acceptance artifact is not distributed')
def test_only_shared_guidance_changes_not_market_calculation_or_protocol():
    def without_guidance(path):
        module=ast.parse(path.read_text(encoding='utf-8'))
        module.body=[n for n in module.body if not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MARKET_GUIDANCE' for t in n.targets))]
        return ast.dump(module,include_attributes=False)
    assert without_guidance(ART/'market_baseline-before.py')==without_guidance(ROOT/'src/shopping_agent/market_baseline.py')


def test_scope_instruction_covers_target_excerpt_unknown_and_whole_cohort():
    for phrase in ('覆盖全部成员','目标商品的model/condition/specs','samples节选','节选不是全部成员的属性统计',
                   '型号、配置、成色、配件及交易条件全部相同','UNKNOWN必须保留为未知','部分样本声明',
                   'missing_attribute_peers','broad_differences','limitations'):
        assert phrase in MARKET_GUIDANCE
    assert '不改变现有条件判断状态定义' in MARKET_GUIDANCE
    assert '不发起额外工具或模型调用' in MARKET_GUIDANCE


@pytest.mark.skipif(not all(path.is_file() for path in [ROOT/'data/artifacts/p3-one-real-1879-20261025/actual-request.json', ROOT/'data/artifacts/p3-formal-load-20261025/live-overviews.json']), reason='Private historical acceptance artifacts are not distributed')
def test_1879_saved_input_already_exposes_partial_attributes_and_stats_stay_frozen():
    actual=json.loads((ROOT/'data/artifacts/p3-one-real-1879-20261025/actual-request.json').read_text(encoding='utf-8'))
    frozen=copy.deepcopy(actual)
    ref=json.loads(actual['evidence'][0]['data']['evidence_json'])['local_market_reference']
    assert ref['condition']=='opened' # The target's condition is NOT a cohort claim.
    assert ref['missing_attribute_peers']==20
    assert any('20 件存在新旧或所选属性缺失' in s for s in ref['limitations'])
    assert ref['broad']['count']==28 and ref['broad']['summary']['median']==325
    assert ref['strict']['count']==4 and ref['strict']['summary']['median']==324
    data=json.loads((ROOT/'data/artifacts/p3-formal-load-20261025/live-overviews.json').read_text(encoding='utf-8'))['3']
    result=project_market(data['cards'],data['project']['goal'],data['market']['as_of'])
    assert result==data['market']
    assert result['profiles']['2009']['condition']==result['profiles']['2472']['condition']=='unknown'
    current=bounded_reference(result['references']['1879'])
    assert current['missing_attribute_peers']==20
    assert current['broad']['member_ids']==ref['broad']['member_ids']
    assert current['strict']['summary']==ref['strict']['summary']
    assert actual==frozen # Historical real requests/outputs are never rewritten.


@pytest.mark.parametrize('attrs,missing',[(CASES[0],'成色'),(CASES[1],'容量'),(CASES[2],'尺码'),(CASES[3],'夹持开口')])
def test_unknown_peer_property_is_not_inherited_from_target_or_known_excerpt(attrs,missing):
    unknown=dict(attrs);unknown.pop(missing)
    # The shared fixture's default title says "自用", itself an opened/used claim.
    # Remove that declaration when constructing genuinely unknown condition.
    rows=[saved(1,attrs,title='离线商品',price=100),saved(2,attrs,title='离线商品',price=110),saved(3,unknown,title='离线商品',price=120)]
    result=project_market(rows,'比较明确的保存商品','2026-10-25T00:00:00Z')
    ref=bounded_reference(result['references']['1'])
    assert ref['broad']['member_ids']==[2,3] and ref['strict']['member_ids']==[2]
    assert ref['missing_attribute_peers']>0 and any('缺失' in s for s in ref['limitations'])
    assert '宽泛层允许部分属性未知' in MARKET_GUIDANCE
    assert ref['broad']['summary']['median']==115


def test_mixed_known_nondecisive_attributes_remain_disclosed_not_common_properties():
    attrs=dict(CASES[2],颜色='黑色')
    other=dict(attrs,颜色='灰色')
    result=project_market([saved(1,attrs),saved(2,attrs),saved(3,other)],'已保存的办公椅','t')
    ref=bounded_reference(result['references']['1'])
    assert ref['broad']['member_ids']==[2,3] and ref['strict']['member_ids']==[2]
    assert ref['broad_difference_count']==1 and ref['broad_differences'][0]['listing_id']==3
    assert '部分样本声明' in MARKET_GUIDANCE
