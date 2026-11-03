import {expect,it} from 'vitest';
import {conditionKey,preserveConditionWording} from './goalConditionComparison';
it('recognizes capacity abbreviations and whitespace without changing the saved wording',()=>{
 const original='硬盘存储容量256GB以上';expect(conditionKey(original)).toBe(conditionKey('硬盘存储容量 256G 以上'));
 expect(preserveConditionWording(['硬盘存储容量256G以上','芯片至少为 M3'],[original])).toEqual([original,'芯片至少为 M3']);
});
it.each([
 ['硬盘256GB以上','硬盘512GB以上'],['硬盘256GB以上','硬盘256GB以下'],['内存16GB','硬盘16GB'],
 ['芯片至少为 M3','芯片至少为 M3 Pro'],['重量256G','重量256GB'],['硬盘256GB','硬盘256GiB'],['硬盘256GB','硬盘256Gb'],
])('does not merge distinct requirements: %s and %s',(a,b)=>expect(conditionKey(a)).not.toBe(conditionKey(b)));
