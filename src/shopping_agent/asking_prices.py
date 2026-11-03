"""Select one saved asking quote per item, without changing historical records."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re


def asking_amount(value):
    """Only an unambiguous single cash asking price, never an original/deposit/range."""
    if value is None or isinstance(value,bool):return None
    text=str(value).strip()
    match=re.fullmatch(r'[¥￥]?\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(万)?\s*(?:元)?',text)
    if not match:return None
    try:amount=Decimal(match[1].replace(',',''))*(10000 if match[2] else 1)
    except InvalidOperation:return None
    return amount if amount.is_finite() and 0<amount<=Decimal('1e12') else None


def number(amount):
    return int(amount) if amount==amount.to_integral() else float(amount)


def stamp(value):
    try:return datetime.fromisoformat(value) if value else None
    except (ValueError,TypeError):return None


def select_quote(offers):
    """Source time when comparable; recorded time as explicitly limited fallback.

    Missing clocks never become evidence of recency. Equal-clock conflicts do
    not choose a cheaper price. A latest ambiguous quote suppresses old prices.
    """
    if not offers:return dict(status='missing',amount=None,valid=False,reason='没有保存报价',warnings=[])
    source=[stamp(o.get('observed_at')) for o in offers]
    comparable=all(source) and len({bool(t.tzinfo) for t in source})==1
    times=source if comparable else [stamp(o.get('recorded_at')) for o in offers]
    warnings=[]
    if not comparable:warnings.append('源时间缺失或时区不可比；仅按保存时间作有限排序，不声称源报价最新')
    if not all(times) or len({bool(t.tzinfo) for t in times if t})!=1:
        return dict(status='unknown_time',amount=None,valid=False,reason='报价时间不足以确定当前价格',warnings=warnings)
    normalized=[t.astimezone(timezone.utc) if t.tzinfo else t for t in times]
    newest=max(normalized);latest=[o for o,t in zip(offers,normalized) if t==newest]
    values={asking_amount(o.get('price_text')) for o in latest}
    valid=next(iter(values)) if len(values)==1 else None
    status='valid' if valid is not None else 'conflict' if len(values)>1 else 'ambiguous'
    # Deterministic provenance only, not a price preference.
    chosen=max(latest,key=lambda o:(o.get('kind')=='snapshot',o.get('record_id',0)))
    return dict(status=status,valid=status=='valid',amount=str(valid) if valid is not None else None,
        price_text=chosen.get('price_text'),source_kind=chosen.get('kind'),record_id=chosen.get('record_id'),
        run_id=chosen.get('run_id'),observed_at=chosen.get('observed_at'),recorded_at=chosen.get('recorded_at'),
        time_basis='source_time' if comparable else 'recorded_time_fallback',
        reason='同一最新时点报价冲突，待确认' if status=='conflict' else '最新保存报价不是明确的单件售价' if status=='ambiguous' else '按可比较时间选择的保存挂牌价',
        warnings=warnings,conflicting_prices=sorted(str(v) if v is not None else '非明确售价' for v in values) if status=='conflict' else [],
        observation_count=len(offers))


def load_asking_quotes(conn,run_ids):
    if not run_ids:return {}
    offers={}
    for start in range(0,len(run_ids),800):
        scope=run_ids[start:start+800];marks=','.join('?' for _ in scope)
        for r in conn.execute(f'''SELECT ls.id,ls.listing_id,ls.run_id,ls.price_text,ls.collected_at,
            mi.observed_at FROM listing_snapshots ls LEFT JOIN monitor_import_records mi ON mi.snapshot_id=ls.id
            WHERE ls.run_id IN ({marks})''',scope):
            offers.setdefault(r['listing_id'],[]).append(dict(kind='snapshot',record_id=r['id'],run_id=r['run_id'],
                price_text=r['price_text'],observed_at=r['observed_at'] or r['collected_at'],recorded_at=r['collected_at']))
        for r in conn.execute(f'SELECT * FROM monitor_price_observations WHERE run_id IN ({marks})',scope):
            offers.setdefault(r['listing_id'],[]).append(dict(kind='price_observation',record_id=r['id'],run_id=r['run_id'],
                price_text=r['price_text'],observed_at=r['observed_at'],recorded_at=r['imported_at']))
    return {listing:select_quote(rows) for listing,rows in offers.items()}


def apply_quote(card,quote):
    card['current_quote']=quote
    if quote and quote['valid']:
        amount=Decimal(quote['amount'])
        # Preserve equivalent snapshot spelling, preventing formatting-only churn.
        if asking_amount(card.get('price_text'))!=amount:card['price_text']=quote['price_text']
        card['price_value']=number(amount)
    elif quote:
        card['price_value']=None
    return card
