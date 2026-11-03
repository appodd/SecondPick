import {expect,it} from 'vitest';
import {reportOpening} from './overviewReport';
it('preserves the entire opening including finite scope and seller qualifications',()=>{const opening='商品 #2 可有条件保留；卖家声称功能正常，尚不足以决定购买。本次仅评估这一件，不代表全市场。';expect(reportOpening(opening+'\n\n详细依据')).toBe(opening)});
it('does not turn a later product description or an oversized opening into a conclusion',()=>{expect(reportOpening('## 研究背景\n\n商品 #2 很便宜。')).toBeNull();expect(reportOpening('很长的段落'.repeat(120))).toBeNull()});
