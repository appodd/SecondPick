import {expect,it} from 'vitest';import {agentIntent} from './agentIntent';import {researchConclusion,researchOrigin,researchPurpose} from './researchPresentation';import type {Study} from '../../api/projectClient';
it('questions about monitor operation never imply a configuration change',()=>expect(agentIntent('为什么监控没有结果？')).toBe('answer'));
it('explicit changes route to a configuration preview',()=>{expect(agentIntent('把监控改为单次')).toBe('monitor');expect(agentIntent('预算调到400元')).toBe('goal')});
it('deeper investigation is distinct from normal comparison',()=>{expect(agentIntent('深入调查这件商品')).toBe('research');expect(agentIntent('比较这两件商品')).toBe('answer')});
it('unknown task origin is not invented as autonomous',()=>{expect(researchOrigin({origin:null} as Study)).toBe('来源未记录');expect(researchOrigin({origin:'confirmed_snapshot'} as Study)).toBe('用户发起');expect(researchOrigin({origin:'automatic_snapshot'} as Study)).toBe('Agent 自主研究')});
it('the visible conclusion is bounded while the original remains available',()=>{expect(researchConclusion('建议先核实。\n\n完整证据')).toBe('建议先核实。');expect(researchPurpose({instruction:'上下文\n用户本次问题：核对配件\n所追问的报告：#1'} as Study)).toBe('核对配件')});
