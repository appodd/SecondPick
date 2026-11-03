import {expect,it} from "vitest";
import type {VisualView} from "./VisualEvidence";
import {validObservations,importantObservations,comparisonObservations} from "./visualPresentation";
const hash='b'.repeat(64);
function view():VisualView{return {task_id:1,listing_id:2,goal_revision:1,state:'image_observation',execution_enabled:false,approval_allowed:false,approval_blocked_reason:'offline',images:[{media_id:8,sha256:hash,width:24,height:16,source_url:'https://img.alicdn.com/mock'}],observations:[{id:'visual:2:4:1:aaa',listing_id:2,study_id:4,run_id:'1152921504606846980',media_id:8,sha256:hash,visible_content:'',limited_inference:'',uncertainty:'未展示关键角度',provider:'deepseek',model:'deepseek-flash',status:'unreadable',subject:'surface',origin:'pixels',source_type:'image_observation',affects_criteria:['soft_1'],freshness:'fresh',review_state:'accepted',independently_verified:false,mode:'mock',references:[]}],rejected_observations:0,unavailable_images:0,failures:[]};}
it.each(['unreadable','not_shown'])('fresh %s remains uncertainty even when it names a criterion',status=>{
  const d=view();d.observations[0].status=status;const checked=validObservations(d,1,2);
  expect(checked).toHaveLength(1);expect(importantObservations(checked)).toEqual([]);expect(comparisonObservations(checked)).toEqual([]);
});
it('same image and listing with a replaced image version cannot enter either summary',()=>{
  const d=view();d.observations[0].status='visible';d.observations[0].visible_content='MOCK';d.images[0].sha256='a'.repeat(64);
  expect(importantObservations(validObservations(d,1,2))).toEqual([]);expect(comparisonObservations(validObservations(d,1,2))).toEqual([]);
});
