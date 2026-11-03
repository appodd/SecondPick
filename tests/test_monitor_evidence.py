"""P0 offline acceptance. All writes use pytest's isolated database directory."""
import asyncio
import json
from pathlib import Path
import socket
import sqlite3
import subprocess

import pytest

from shopping_agent.assessment import evidence_signature
from shopping_agent.candidate_context import build_candidate_evidence, build_candidate_index
from shopping_agent.config import AppConfig
from shopping_agent.db import connect, create_research_task, initialize
from shopping_agent.goofish_evidence import DetailEvidenceTap
from shopping_agent.goofish_import import _normalize, import_goofish_jsonl
from shopping_agent.goofish_pipeline import EvidenceJournal
from shopping_agent.monitor_evidence import load_monitor_evidence
from shopping_agent.project_research import ProjectResearch
from shopping_agent.web.schemas import ListingEvidence


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # Windows asyncio creates a local socketpair for its own event loop; build
    # it before blocking all connection attempts by the code under test.
    loop = asyncio.new_event_loop()
    def forbidden(*a, **kw):
        pytest.fail('P0 must not access network or launch CLI/browser processes')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    yield loop
    loop.close()


@pytest.fixture
def env(tmp_path):
    config = AppConfig(database_path=tmp_path / 'isolated.sqlite', media_dir=tmp_path / 'media')
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task = create_research_task(conn, 'NS2 Pro', 'good controller', '')
    return config, task, tmp_path / 'products.jsonl'


def record(stage='card', at='2026-10-24T10:00:00'):
    return {'任务名称': 'monitor', '搜索关键字': 'NS2 Pro', '爬取时间': at,
            '_collection_stage': stage,
            '商品信息': {'商品ID': '123', '商品链接': 'https://www.goofish.com/item?id=123',
                         '商品标题': 'NS2 Pro', '当前售价': '300'}}


def rich(stage='seller_enriched', at='2026-10-24T10:00:00'):
    r = record(stage, at)
    r['商品信息'].update({'商品描述': 'Seller says unused; shipping extra.', '商品属性': {'品牌': 'Nintendo', 'token': 'private'},
        '商品图片列表': ['https://img.alicdn.com/item.jpg', 'http://127.0.0.1/private'],
        '商品主图链接': 'https://img.alicdn.com/item.jpg', '商品标签': ['包邮'], '商品原价': '499',
        '浏览量': 123, '“想要”人数': 0, 'cookies': 'private'})
    r['卖家信息'] = {'卖家信用等级': 'excellent', '卖家收到的评价总数': 20,
        '卖家个性签名': 'private', '卖家头像链接': 'private', '卖家收到的评价列表': [{'评价者昵称': 'private'}],
        '卖家发布的商品列表': [{'商品标题': 'Another controller', '商品价格': '200', '商品状态': '在售',
                                 '商品ID': 'private', 'cookie': 'private'}]}
    return r


def ingest(env, records, journal=False):
    config, task, path = env
    if journal:
        for r in records:
            EvidenceJournal(path).append(r, r['_collection_stage'], round_id='round-1')
    else:
        with path.open('a', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return import_goofish_jsonl(config, path=path, task_id=task, keyword='NS2 Pro')


def card(env):
    return build_candidate_index(env[0], task_id=env[1])['candidates'][0]


def test_bridge_import_context_and_real_request_use_only_saved_public_fields(env):
    assert ingest(env, [rich()], journal=True)['imported'] == 1
    c = card(env)
    e = build_candidate_evidence(env[0], task_id=env[1], listing_ids=[c['listing_id']])['candidates'][0]
    ListingEvidence.model_validate(e)
    fields = e['monitor_evidence']['fields']
    assert fields['monitor_detail']['商品描述'].startswith('Seller says')
    assert fields['monitor_detail']['商品属性'] == {'品牌': 'Nintendo'}
    assert fields['monitor_detail']['商品图片列表'] == ['https://img.alicdn.com/item.jpg']
    assert fields['monitor_detail']['“想要”人数'] == '0'
    assert fields['seller_public']['卖家发布的商品列表'] == [{'商品标题': 'Another controller', '商品价格': '200', '商品状态': '在售'}]
    assert not e['has_detail'] and e['detail'] is None and e['detail_status'] == 'not_captured'
    assert e['monitor_evidence']['independently_verified'] is False
    assert e['monitor_evidence']['image_content_analyzed'] is False
    source = e['monitor_evidence']['field_sources']['monitor_detail']['商品描述']
    assert source['observed_at'] == '2026-10-24T10:00:00' and source['snapshot_id'] > 0
    assert 'private' not in env[2].read_text(encoding='utf-8')
    # Exercise the production request builder, without constructing/starting a
    # scheduler or calling runtime.run. Real CLI and sockets are blocked above.
    from shopping_agent.codex_runtime import CodexRuntime
    p = object.__new__(ProjectResearch)
    p.config = env[0]
    p.clock = lambda: '2026-10-24T12:00:00+00:00'
    p.require = lambda _: {'goal': 'controller', 'city': ''}
    p.runtime = CodexRuntime(env[0].database_path.parent)
    snapshot = {'revision': 1, 'goal': 'controller', 'hard_json': '[]', 'soft_json': '[]', 'budget': None}
    request = p._request(env[1], [c], 'Use saved evidence', snapshot)
    payload = request.model_dump_json()
    assert 'Seller says unused' in payload and 'Nintendo' in payload and 'image_content_analyzed' in payload
    with connect(env[0].database_path) as conn:
        for table in ('detail_snapshots', 'media_image_evidence', 'operations', 'browser_jobs', 'research_assessments'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        # Importing a saved URL is not downloading or analyzing its pixels.
        media = conn.execute('SELECT source_url,local_path FROM media_assets').fetchall()
        assert [tuple(row) for row in media] == [('https://img.alicdn.com/item.jpg', '')]
    assert not [path for path in env[0].media_dir.rglob('*') if path.is_file()]


def test_search_stage_cannot_claim_detail_or_seller_enrichment(env):
    r = rich('search_card')
    r['_source_round_id'] = 'round-1'
    ingest(env, [r], journal=True)
    candidate = card(env)
    evidence = candidate['monitor_evidence']
    fields = evidence['fields']
    assert set(fields) == {'search_card', 'monitor_detail'}
    assert fields['monitor_detail'] == {
        '商品主图链接': 'https://img.alicdn.com/item.jpg',
        '商品图片列表': ['https://img.alicdn.com/item.jpg'],
    }
    assert 'seller_public' not in fields
    assert not {'商品描述', '商品属性', '浏览量'} & fields['monitor_detail'].keys()
    assert all(source['stage'] == 'search_card' and source['attribution'] == 'seller_uploaded_image_url'
               for source in evidence['field_sources']['monitor_detail'].values())
    assert candidate['detail_status'] == 'not_captured'
    assert evidence['independently_verified'] is False
    assert evidence['image_content_analyzed'] is False
    with connect(env[0].database_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM detail_snapshots').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM media_image_evidence').fetchone()[0] == 0


def test_missing_partial_invalid_extras_degrade_without_losing_listing(env):
    r = rich()
    r['商品信息'].update({'商品描述': {}, '商品属性': [], '商品图片列表': [None, {}, 'javascript:x'], '商品主图链接': None, '浏览量': float('nan'), '“想要”人数': None})
    r['卖家信息'] = {'卖家发布的商品列表': 'invalid'}
    assert ingest(env, [r])['imported'] == 1
    assert 'monitor_detail' not in card(env)['monitor_evidence']['fields']
    assert card(env)['price_value'] == 300


def test_duplicate_restart_partial_update_and_old_arrival(env):
    ingest(env, [rich()])
    original = card(env)
    signature = ProjectResearch.signature(original)
    assert ingest(env, [])['imported'] == 0
    initialize(env[0].database_path)  # Simulated restart/schema load.
    assert ingest(env, [])['imported'] == 0
    later = record(at='2026-10-24T11:00:00')
    later['商品信息']['浏览量'] = 200
    ingest(env, [later])
    current = card(env)
    assert current['monitor_evidence']['fields']['monitor_detail']['商品描述'].startswith('Seller says')
    assert current['monitor_evidence']['fields']['monitor_detail']['浏览量'] == '200'
    old = rich(at='2026-10-23T11:00:00')
    old['商品信息']['商品描述'] = 'old description imported late'
    ingest(env, [old])
    assert card(env)['monitor_evidence']['fields'] == current['monitor_evidence']['fields']
    assert ProjectResearch.signature(card(env)) == ProjectResearch.signature(current)
    # Timestamp/provenance changes alone do not change the project signature.
    newer = rich(at='2026-10-25T11:00:00')
    newer['商品信息']['浏览量'] = 200
    ingest(env, [newer])
    assert ProjectResearch.signature(card(env)) == ProjectResearch.signature(current)
    assert signature != ProjectResearch.signature(current)


def test_legacy_migration_preserves_fingerprint_and_both_signature_paths(env):
    ingest(env, [record()])
    original = card(env)
    assert 'monitor_evidence' not in original
    config, task, path = env
    with connect(config.database_path) as conn:
        conn.execute('ALTER TABLE monitor_import_records DROP COLUMN evidence_json')
        before = evidence_signature(conn, task)
        assert load_monitor_evidence(conn, original['source_run_ids']) == {}
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        assert evidence_signature(conn, task) == before
        assert conn.execute('SELECT evidence_json FROM monitor_import_records').fetchone()[0] == '{}'
    assert ingest(env, [])['imported'] == 0
    assert ProjectResearch.signature(card(env)) == ProjectResearch.signature(original)
    assert 'monitor_evidence' not in _normalize(record(), 'NS2 Pro', None)


def test_updated_description_invalidates_signature_without_queueing_or_ai(env):
    ingest(env, [rich()])
    old = ProjectResearch.signature(card(env))
    r = rich(at='2026-10-25T10:00:00')
    r['商品信息']['商品描述'] = 'Seller now discloses repaired buttons'
    ingest(env, [r])
    assert ProjectResearch.signature(card(env)) != old
    with connect(env[0].database_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM operations').fetchone()[0] == 0
    assert not env[0].database_path.with_suffix('.secondpick.sqlite').exists()


def test_same_listing_incremental_detail_and_seller_evidence_reaches_project_request(env):
    from shopping_agent.codex_runtime import CodexRuntime
    ingest(env, [record()])
    original = card(env)
    old_signature = ProjectResearch.signature(original)
    ingest(env, [rich(at='2026-10-25T10:00:00')], journal=True)
    enriched = card(env)
    assert enriched['listing_id'] == original['listing_id']
    assert len(build_candidate_index(env[0], task_id=env[1])['candidates']) == 1
    assert ProjectResearch.signature(enriched) != old_signature
    p = object.__new__(ProjectResearch)
    p.config = env[0]
    p.clock = lambda: '2026-10-25T12:00:00+00:00'
    p.require = lambda _: {'goal': 'controller', 'city': ''}
    p.runtime = CodexRuntime(env[0].database_path.parent)
    snapshot = {'revision': 1, 'goal': 'controller', 'hard_json': '[]', 'soft_json': '[]', 'budget': None}
    request = p._request(env[1], [enriched], 'Inspect saved evidence', snapshot)
    data = json.loads(request.evidence[0].data['evidence_json'])
    assert data['monitor_evidence']['fields']['monitor_detail']['商品属性'] == {'品牌': 'Nintendo'}
    assert data['monitor_evidence']['fields']['seller_public']['卖家收到的评价总数'] == '20'
    signature = ProjectResearch.signature(enriched)
    late = rich(at='2026-10-23T10:00:00')
    late['商品信息']['商品描述'] = 'Older claim'
    ingest(env, [late])
    assert ProjectResearch.signature(card(env)) == signature
    ingest(env, [rich(at='2026-10-26T10:00:00')])
    assert ProjectResearch.signature(card(env)) == signature
    with connect(env[0].database_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM listings').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM detail_snapshots').fetchone()[0] == 0
    assert not env[0].database_path.with_suffix('.secondpick.sqlite').exists()


def test_existing_response_tap_preserves_return_and_binds_exact_item_only(offline):
    calls = []
    async def getter(data, *keys, default=None):
        calls.append(keys)
        for key in keys:
            data = data.get(key, {})
        return data
    tap = DetailEvidenceTap()
    response = {'ret': ['SUCCESS::ok'], 'data': {'itemDO': {'itemId': '123', 'desc': 'Full saved seller description',
        'itemLabelExtList': [{'propertyText': '品牌', 'text': 'Nintendo'}], 'cookie': 'private'}}}
    result = offline.run_until_complete(tap.wrap(getter)(response, 'data', 'itemDO'))
    assert result is response['data']['itemDO'] and calls == [('data', 'itemDO')]
    wrong = record(); wrong['商品信息']['商品ID'] = '456'
    tap.enrich(wrong)
    assert '商品描述' not in wrong['商品信息']
    target = record()
    tap.enrich(target)
    assert target['商品信息']['商品描述'] == 'Full saved seller description'
    assert 'private' not in json.dumps(target)
    again = record(); tap.enrich(again)
    assert '商品描述' not in again['商品信息']
    response['ret'] = ['FAIL_SYS_USER_VALIDATE']
    offline.run_until_complete(tap.wrap(getter)(response, 'data', 'itemDO'))
    assert not tap.pending


def test_real_saved_ns2_database_and_journal_compatibility_in_isolated_copy(tmp_path):
    from shopping_agent.candidate_context import _load_scoped_candidates
    root = Path(__file__).resolve().parents[1]
    live = root / 'data/secondpick-preview/shopping.sqlite'
    samples = list((root / 'data/secondpick-preview/monitor-engine').glob('*/monitor-3/products.jsonl'))
    if not live.exists() or not samples:
        pytest.skip('Local saved acceptance data unavailable; synthetic compatibility tests still run')
    target = tmp_path / 'saved-copy.sqlite'
    with sqlite3.connect(live.resolve().as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(target) as dest:
            source.backup(dest)
    config = AppConfig(database_path=target)
    with connect(target) as conn:
        runs = [r[0] for r in conn.execute('SELECT run_id FROM task_runs WHERE task_id=3')]
        before, _ = _load_scoped_candidates(conn, runs)
        old_signature = evidence_signature(conn, 3)
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                  for t in ('listings', 'listing_snapshots', 'monitors', 'detail_snapshots', 'task_runs')}
    initialize(target)
    after = build_candidate_index(config, task_id=3)['candidates']
    # The local acceptance database can gain listings after its original capture.
    # Migration must preserve the exact copied cohort, not an old live count.
    assert before and len(before) == len(after)
    assert before == after  # Empty additive field does not change any old candidate.
    assert [ProjectResearch.signature(c) for c in before] == [ProjectResearch.signature(c) for c in after]
    with connect(target) as conn:
        assert evidence_signature(conn, 3) == old_signature
    records = [json.loads(s) for s in samples[0].read_text(encoding='utf-8').splitlines()[:20]]
    path = tmp_path / 'saved-sample.jsonl'
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in records)+'\n', encoding='utf-8')
    imported = import_goofish_jsonl(config, path=path, task_id=3,
                                  keyword=records[0]['搜索关键字'], source_task=records[0]['任务名称'])
    assert imported['imported'] == 0 and imported['duplicates'] == len(records)
    with connect(target) as conn:
        assert counts == {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in counts}
    assert not target.with_suffix('.secondpick.sqlite').exists()


def test_worker_bridge_still_imports_without_application_package(monkeypatch):
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'src/shopping_agent/goofish_pipeline.py'
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location('standalone_p0_pipeline', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.EvidenceJournal and module.item_fields
