import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {ImageEvidenceNotice,type ImageProof} from './ImageEvidenceNotice';
afterEach(cleanup);
it('separates URL, file, constructed attachment and unverified real observation',()=>{
 const images:ImageProof[]=[{id:1},{id:2,evidence:{state:'saved',observed:false}},{id:3,evidence:{state:'saved',observed:false,input_uses:[{study_id:7,goal_revision:2,input_constructed:true,remote_received:false,observed:false}]}},{id:4,evidence:{state:'failed',observed:false}}];
 render(<ImageEvidenceNotice images={images}/>);
 expect(screen.getByText(/图片 1：仅有图片链接/)).toBeInTheDocument();
 expect(screen.getByText(/图片 2：图片文件已保存并校验/)).toBeInTheDocument();
 expect(screen.getByText(/图片 3：/)).toHaveTextContent('附件已构造');
 expect(screen.getByText(/图片 3：/)).toHaveTextContent('尚未确认送达模型');
 expect(screen.getByText(/视觉观察：/)).toHaveTextContent('尚无已验证的真实记录');
 expect(screen.getByText(/图片 4：图片保存失败/)).toBeInTheDocument();
});
it('does not upgrade historical local paths or invalid files to saved/current observations',()=>{
 render(<ImageEvidenceNotice images={[{id:1,evidence:{state:'legacy_unverified',observed:false}},{id:2,evidence:{state:'unreadable',observed:false}}]}/>);
 expect(screen.getByText(/图片 1：/)).toHaveTextContent('尚未建立校验依据');
 expect(screen.getByText(/图片 2：/)).toHaveTextContent('校验不符');
});
