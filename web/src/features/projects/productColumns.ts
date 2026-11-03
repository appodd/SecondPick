export const optionalProductColumns=[['match','条件匹配'],['condition','成色声明'],['repair','维修与待核实'],['source','采集来源']] as const;
export type ProductColumn=typeof optionalProductColumns[number][0];
export function productColumns(params:URLSearchParams):ProductColumn[]{
  if(params.has('columns'))return optionalProductColumns.map(c=>c[0]).filter(c=>(params.get('columns')??'').split(',').includes(c));
  return params.get('fields')==='hidden'?[]:['match'];
}
