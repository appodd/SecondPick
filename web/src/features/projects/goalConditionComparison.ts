/** Only normalize unambiguous formatting, not general requirement semantics. */
export function conditionKey(text:string) {
  let value=text.normalize('NFKC').replace(/\s+/g,'');
  if(/存储|硬盘|内存|SSD|RAM/i.test(value) && !/重量|公斤|毫克|weight/i.test(value)) {
    // G is a common GB abbreviation in computer-capacity requirements.
    // Keep GiB, Gb (bits), values, and comparison operators distinct.
    value=value.replace(/(\d+(?:\.\d+)?)(?:GB|gb|G|g)(?![a-zA-Z])/g,'$1GB');
  }
  return value;
}
export function conditionValues(values:string[]) {
  const seen=new Set<string>();
  return values.map(s=>s.trim()).filter(s=>{const key=conditionKey(s);if(!s||seen.has(key))return false;seen.add(key);return true});
}
export function containsCondition(values:string[],text:string){return values.some(s=>conditionKey(s)===conditionKey(text))}
export function preserveConditionWording(next:string[],before:string[]) {
  return conditionValues(next.map(s=>before.find(old=>conditionKey(old)===conditionKey(s))??s));
}
