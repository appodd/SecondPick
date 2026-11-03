"""Read-only projection of saved research onto a goal and current evidence versions.

No queue, model calls, recapture, or mutation of historical version states.
"""
import json
import math
import re
from shopping_agent.assessment import ResearchResult

def projection(conn, task_id, cards, revision, signature, budget):
    states, prior_inputs, ever_evaluated, ever_summarized, active = {}, set(), set(), set(), set()
    rows = conn.execute('SELECT s.*,b.goal_revision FROM studies s LEFT JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? ORDER BY s.id', (task_id,)).fetchall()
    for row in rows:
        if row['kind']=='visual' or row['kind'].startswith('seller:'):
            continue
        versions = json.loads(row['versions_json'])
        result = json.loads(row['result_json']) if row['result_json'] else {}
        try:
            evaluated = {a.listing_id for a in ResearchResult.model_validate(result.get('research')).assessments}
        except (ValueError, TypeError):
            evaluated = set()  # Text mentions and malformed legacy payloads are not item research.
        for listing_id, evidence_signature in versions:
            key = (listing_id,evidence_signature)
            if row['state']=='completed':
                prior_inputs.add(key)
                (ever_evaluated if listing_id in evaluated else ever_summarized).add(listing_id)
            if row['goal_revision']==revision:
                if row['state'] in {'queued','running'}:
                    active.add(key)
                state = ('queued' if row['state'] in {'queued','running'} else 'blocked' if row['state']=='failed'
                    else 'evaluated' if row['state']=='completed' and listing_id in evaluated else 'summarized' if row['state']=='completed' else 'waiting')
                # An input/summary (or failed revisit) cannot erase an assessment
                # for the same frozen goal and evidence. Execution is separate.
                if states.get(key) != 'evaluated':
                    states[key] = state
    for key in active:
        if states.get(key) != 'evaluated':
            states[key] = 'queued'
    buckets = dict(rule_excluded=0,waiting=0,needs_information=0,under_ai=0,evaluated=0,summarized=0,blocked=0)
    item_states = {}
    for card in cards:
        key = (card['listing_id'],signature(card))
        price = card.get('price_value')
        usable = isinstance(price,(int,float)) and math.isfinite(price) and price>0 and not re.search(r'起|定金|订金|首付|每[月天]|/(?:月|天)|\d\s*[-~～至]\s*\d',card.get('price_text') or '')
        default = 'rule_excluded' if usable and budget is not None and price>budget else 'waiting' if usable and card.get('comparison_group') else 'needs_information'
        state = states.get(key,default)
        item_states[card['listing_id']] = state
        buckets['under_ai' if state=='queued' else state] += 1
    return dict(coverage=buckets,states=item_states,history=dict(
        evaluated=len(ever_evaluated),summarized_only=len(ever_summarized-ever_evaluated),
        reusable_evidence=sum((c['listing_id'],signature(c)) in prior_inputs for c in cards)))
