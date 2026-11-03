"""Read saved monitor supplements without manufacturing independent snapshots."""
import json
from datetime import datetime, timezone


def load_monitor_evidence(conn, run_ids):
    # Also safe for read-only, pre-migration databases.
    if 'evidence_json' not in {r[1] for r in conn.execute('PRAGMA table_info(monitor_import_records)')}:
        return {}
    rows = []
    for start in range(0, len(run_ids), 800):
        scope = run_ids[start:start + 800]
        rows.extend(conn.execute(f'''SELECT mi.*,ls.listing_id,ls.run_id FROM monitor_import_records mi
            JOIN listing_snapshots ls ON ls.id=mi.snapshot_id
            WHERE ls.run_id IN ({','.join('?' for _ in scope)}) AND mi.evidence_json!='{{}}' ''', scope))

    def timestamp(value):
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    def newer(row, previous):
        left, right = timestamp(row['observed_at']), timestamp(previous['observed_at'])
        if left is None or right is None:
            return left is not None if left != right else row['snapshot_id'] > previous['snapshot_id']
        if bool(left.tzinfo) == bool(right.tzinfo):
            if left.tzinfo:
                left, right = left.astimezone(timezone.utc), right.astimezone(timezone.utc)
            if left != right:
                return left > right
        # Mixed timezone semantics cannot establish source recency; retain
        # provenance and use import order only as an explicitly limited fallback.
        return row['snapshot_id'] > previous['snapshot_id']

    result = {}
    for row in sorted(rows, key=lambda r: r['snapshot_id']):
        try:
            saved = json.loads(row['evidence_json'])
        except (ValueError, TypeError):
            continue
        if not isinstance(saved, dict) or saved.get('version') != 1 or not isinstance(saved.get('fields'), dict):
            continue
        target = result.setdefault(row['listing_id'], dict(fields={}, field_sources={},
            source='monitor_supplement', independently_verified=False, image_content_analyzed=False,
            limits=dict(description_chars=10000, attribute_count=40, image_urls=12,
                        seller_item_summaries=20, seller_inventory_is_sample=True),
            limitations='Saved seller claims/platform displays, not independent verification. Image URLs are not image observations. '
                         'Missing fields were not obtained; older nonempty fields retain their own observation time. '
                         'Incomparable source timezones use import order, not proven source recency.'))
        for group, values in saved['fields'].items():
            if group not in {'search_card', 'monitor_detail', 'seller_public'} or not isinstance(values, dict):
                continue
            for key, value in values.items():
                previous = target['field_sources'].get(group, {}).get(key)
                if previous and not newer(row, previous):
                    continue
                target['fields'].setdefault(group, {})[key] = value
                target['field_sources'].setdefault(group, {})[key] = dict(
                    snapshot_id=row['snapshot_id'], run_id=row['run_id'],
                    observed_at=row['observed_at'] if timestamp(row['observed_at']) else None, imported_at=row['imported_at'],
                    time_basis='source_record_time_not_independent_verification_time',
                    capture_scope='search_or_detail_display' if key == '“想要”人数' else group,
                    stage=saved.get('stage'), source='ai-goofish-monitor',
                    attribution=('seller_claim' if group == 'monitor_detail' and key in {'商品描述', '商品属性'} else
                                 'seller_uploaded_image_url' if key in {'商品图片列表', '商品主图链接'} else
                                 'platform_display'), independently_verified=False)
    return {key: value for key, value in result.items() if value['fields']}
