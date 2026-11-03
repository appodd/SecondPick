import {describe,it,expect} from 'vitest';
import {shoppingFixture} from '../../test/shoppingFixture';
import {decisionCandidates,comparisonIds} from './candidateDecision';
import {productColumns} from './productColumns';

describe('decision evidence projection',()=>{
 it('separates nomination and saving without duplicate products',()=>{const d=decisionCandidates(shoppingFixture(),true);expect(d.get(2)).toMatchObject({nominated:true,saved:true});expect(d.get(3)).toMatchObject({nominated:false,saved:true,basis:'none'});expect(d.size).toBe(5)});
 it('uses current item judgments only against current evidence',()=>{const d=shoppingFixture();d.cards[0].research_state='waiting';const item=decisionCandidates(d,true).get(1)!;expect(item.basis).toBe('report');expect(item.reason).toContain('维修记录');});
 it('never promotes a previous goal judgment to a current one',()=>{const d=shoppingFixture();d.goal_context!.current_revision=2;d.goal_context!.report_current=false;expect(decisionCandidates(d,true).get(1)!.basis).toBe('report');});
 it('does not reuse judgments when source continuity is unknown',()=>{expect(decisionCandidates(shoppingFixture(),false).get(1)!.basis).toBe('report')});
 it('keeps seller claims and conflicts as such',()=>{const d=decisionCandidates(shoppingFixture(),true);expect(d.get(1)!.supports[0].judgment.source_type).toBe('seller_claim');expect(d.get(2)!.risks[0].judgment.status).toBe('CONFLICT')});
 it('does not invent advantages from a low price or a favorite',()=>{const d=shoppingFixture();d.cards[2].price_value=1;const item=decisionCandidates(d,true).get(3)!;expect(item.supports).toEqual([]);expect(item.reason).toContain('尚无可用');});
 it('moves non-unknown assertions without references out of supported advantages',()=>{const d=shoppingFixture();d.studies[0].result!.research!.assessments[0].judgments[0].evidence_refs=[];const item=decisionCandidates(d,true).get(1)!;expect(item.supports).toHaveLength(0);expect(item.unknowns).toHaveLength(2)});
 it('does not attach an unrelated study as report evidence',()=>{const d=shoppingFixture();d.cards[0].research_state='waiting';d.report!.study_id=999;expect(decisionCandidates(d,true).get(1)!.basis).toBe('none')});
 it('bounds IDs to project goods while retaining an oversized explicit selection for rejection',()=>{expect(comparisonIds('1,1,2,999,-1,abc',shoppingFixture())).toEqual([1,2]);expect(comparisonIds('1,2,3,4,5',shoppingFixture())).toHaveLength(5)});
 it('keeps historical fields-hidden URLs and validates individual field choices',()=>{expect(productColumns(new URLSearchParams('fields=hidden'))).toEqual([]);expect(productColumns(new URLSearchParams())).toEqual(['match']);expect(productColumns(new URLSearchParams('columns=source,evil,repair'))).toEqual(['repair','source']);expect(productColumns(new URLSearchParams('columns='))).toEqual([])});
});
