import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {views,pageDescriptions} from './projectUi';
import {StatusBadge} from '../../components/status/ExecutionStatus';
afterEach(cleanup);
it('uses one ordered navigation and a single responsibility sentence for every page',()=>{expect(views.map(([key])=>key)).toEqual(['overview','shortlist','products','monitors','research']);for(const [key] of views){expect(pageDescriptions[key].length).toBeLessThan(40);expect(pageDescriptions[key].split('。').filter(Boolean)).toHaveLength(1)}});
it('shows a stop symbol for stopped scheduling, not a checkbox-shaped square',()=>{const {container}=render(<StatusBadge status={{kind:'inactive',label:'监控调度已停止'}}/>);expect(screen.getByText('监控调度已停止')).toBeVisible();expect(container.querySelector('.lucide-circle-stop')).not.toBeNull();expect(container.querySelector('.lucide-square')).toBeNull();expect(screen.queryByRole('checkbox')).toBeNull()});
it('does not call an unconfigured monitor stopped',()=>{const {container}=render(<StatusBadge status={{kind:'inactive',label:'尚无监控'}}/>);expect(container.querySelector('.lucide-circle-minus')).not.toBeNull();expect(container.querySelector('.lucide-circle-stop')).toBeNull()});
