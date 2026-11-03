import type {Study} from '../../api/projectClient';
export function researchOrigin(study:Study){return study.origin?.startsWith('automatic_')?'Agent 自主研究':study.origin==='confirmed_snapshot'?'用户发起':'来源未记录'}
export function researchPurpose(study:Study){const text=study.instruction??'';const marker='用户本次问题：';return (text.includes(marker)?text.split(marker).slice(1).join(marker).split(/\n(?:所追问的报告：|交易地区：|商品条件判断统一口径)/)[0]:text).trim().slice(0,1600)}
export function researchConclusion(content:string){const first=content.split(/\n\s*\n/).find(s=>s.trim())?.trim()??'';return first.length>600?first.slice(0,600)+'…':first}
