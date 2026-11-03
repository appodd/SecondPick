import {expect,it} from 'vitest';
import type {WindowMonitor} from '../../api/projectClient';
import {goalMonitorCoverage} from './goalMonitorCoverage';
const window=(keyword:string)=>({monitor_id:1,name:'search',monitor:{keyword},runs:[]}) as unknown as WindowMonitor;
it('separates a new M2 scope from an existing M1 scope',()=>{
 const result=goalMonitorCoverage('MacBook Pro，接受 M1 或 M2，内存至少32GB',[],[window('MacBook Pro M1')]);
 expect(result.supported).toBe(true);expect(result.items[0].matching).toHaveLength(1);expect(result.items[1].matching).toHaveLength(0);expect(result.items[1].possible).toHaveLength(0);expect(result.items[1].keyword).toBe('MacBook Pro M2');
});
it('retains paused matches to avoid recommending duplicate monitors',()=>{expect(goalMonitorCoverage('MacBook Pro M2',[],[window('MacBook Pro M2')]).items[0].matching).toHaveLength(1)});
it('treats broad searches as possible rather than proven coverage',()=>{const r=goalMonitorCoverage('MacBook Pro M2',[],[window('MacBook Pro')]).items[0];expect(r.matching).toHaveLength(0);expect(r.possible).toHaveLength(1)});
it('does not confuse M2 Pro, M2, or other product categories',()=>{expect(goalMonitorCoverage('MacBook Pro M2 Pro',[],[window('MacBook Pro M2'),window('MacBook Air M2 Pro')]).items[0].matching).toHaveLength(0)});
it.each(['MacBook Pro 不考虑M2，只考虑M1','MacBook Pro M1及以上','预算内找相机'])('keeps ambiguous or unsupported goals uncertain: %s',goal=>{expect(goalMonitorCoverage(goal,[],[]).supported).toBe(false)});
