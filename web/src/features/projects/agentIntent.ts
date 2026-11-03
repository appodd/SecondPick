export function agentIntent(text:string):'answer'|'research'|'monitor'|'goal' {
 if(/^(为什么|什么是|如何|怎么|是否需要|要不要|有必要)/.test(text.trim())&&!/(帮我|请你|请帮|给我)/.test(text))return 'answer';
 const change=/(修改|调整|改成|改为|改到|调到|创建|新建|设置)/.test(text);
 if(change&&/(监控|采集|搜索条件|搜索词)/.test(text))return 'monitor';
 if(change&&/(预算|选购目标|选购条件|硬条件|偏好)/.test(text))return 'goal';
 if(/(深入调查|深入研究|正式研究|补充调查|继续调查|进一步调查|帮我调查|请调查)/.test(text))return 'research';
 return 'answer';
}
