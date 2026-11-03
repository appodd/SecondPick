import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import type {MarketReference} from '../../api/projectClient';
import {MarketReferenceSummary} from './MarketReferenceSummary';
afterEach(cleanup);
const layer={count:2,member_ids:[2,3],summary:{count:2,min:310,max:330,median:320,q1:315,q3:325},position:'样本不足，暂不判断偏低或偏高'};
const reference:MarketReference={target_id:1,as_of:'2026-10-24T00:00:00Z',current_quote:{status:'valid',valid:true,amount:'328.60',reason:'保存报价',warnings:[]},model:'Switch 2 Pro',condition:'opened',state:'available',criteria:{broad:'同代际与新旧层',strict:'盒线明确相同'},broad:layer,strict:layer,peer_total:3,excluded_count:1,exclusion_counts:{'配件单卖':1},excluded:[{listing_id:4,reason:'配件单卖'}],strict_excluded:[],limitations:['挂牌不是成交价；卖家声明未独立核实','图片URL不代表已查看'],data_digest:'test'};
it('separates layers, small samples, sources and traceable peers without AI claims',()=>{
 const select=vi.fn();render(<MarketReferenceSummary reference={reference} select={select}/>);
 expect(screen.getByText(/当前保存挂牌/)).toHaveTextContent('¥328.6');
 expect(screen.getByText(/宽泛可比 2 件/)).toBeInTheDocument();
 expect(screen.getByText(/严格对照 2 件/)).toHaveTextContent('子集');
 expect(screen.getByText(/这是当前本地挂牌统计/)).toHaveTextContent('不表示 AI 已用这些数据更新');
 fireEvent.click(screen.getByRole('button',{name:'#4'}));expect(select).toHaveBeenCalledWith(4);
});
it('does not display an unresolved quote as a known asking price',()=>{
 render(<MarketReferenceSummary compact reference={{...reference,current_quote:{...reference.current_quote!,valid:false,status:'conflict',amount:null}}}/>);
 expect(screen.getByText(/当前保存挂牌/)).toHaveTextContent('待确认');
});
it('explains insufficient identity without claiming an old mixed price baseline',()=>{
 const empty={...layer,count:0,member_ids:[],summary:{count:0,min:null,max:null,median:null,q1:null,q3:null}};
 render(<MarketReferenceSummary reference={{...reference,broad:empty,strict:empty,unavailable_reason:'所售型号未明确'}}/>);
 expect(screen.getByRole('status')).toHaveTextContent('无法建立可靠同款基线：所售型号未明确');
 expect(screen.getByText(/宽泛可比 0 件/)).toHaveTextContent('中位 —');
});
it('does not turn target condition into a common property of partially unknown peers',()=>{
 const partial={...reference,condition:'opened',missing_attribute_peers:1,
  criteria:{broad:'同明确商品身份；未知配置仅作有条件参考',strict:'当前所选维度明确相符'},
  limitations:['宽泛层 1 件存在新旧或所选属性缺失，不属于同质严格样本']};
 const {container}=render(<MarketReferenceSummary reference={partial}/>);
 expect(screen.getByText(/宽泛层 1 件存在新旧或所选属性缺失/)).toBeInTheDocument();
 expect(container).not.toHaveTextContent('全部已拆封');
 expect(container).not.toHaveTextContent('同成色');
 expect(container).not.toHaveTextContent('opened');
 expect(screen.getByText(/严格对照 2 件/)).toHaveTextContent('当前明确维度');
});
