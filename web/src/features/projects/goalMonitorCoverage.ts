import type { WindowMonitor } from '../../api/projectClient';

/** Keyword evidence only. Never infer marketplace recall or arbitrary goal semantics. */
export function goalMonitorCoverage(goal: string, hard: string[], windows: WindowMonitor[]) {
  const text = [goal, ...hard].join(' ');
  const models = [...new Set((text.match(/\bM[1-9](?:\s+(?:Pro|Max|Ultra))?\b/gi) ?? []).map(s => s.toUpperCase().replace(/\s+/g, ' ')))];
  const mac = /macbook/i.test(text);
  // Negation, ranges and minimum generations require semantic confirmation.
  const ambiguous = /(?:不要|不考虑|排除|不接受)[^。；;]*\bM[1-9]|(?:至少|不低于)\s*M[1-9]|\bM[1-9](?:\s+(?:Pro|Max|Ultra))?\s*(?:及以上|以上|起步|或更新)/i.test(text);
  return { supported: mac && models.length > 0 && !ambiguous,
    items: mac && !ambiguous ? models.map(model => {
      const matching = windows.filter(w => {
        const keyword = w.monitor?.keyword ?? '';
        const found = (keyword.match(/\bM[1-9](?:\s+(?:Pro|Max|Ultra))?\b/gi) ?? []).map(s=>s.toUpperCase().replace(/\s+/g,' '));
        return !/不要|不考虑|排除|不接受/.test(keyword) && /macbook/i.test(keyword) && (!/macbook\s*pro/i.test(text) || /macbook\s*pro/i.test(keyword)) && found.includes(model);
      });
      const possible = windows.filter(w => !matching.includes(w) && /macbook/i.test(w.monitor?.keyword ?? '') && !/\bM[1-9]\b/i.test(w.monitor?.keyword ?? ''));
      return { model, matching, possible, keyword: `MacBook${/macbook\s*pro/i.test(text) ? ' Pro' : ''} ${model}` };
    }) : [] };
}
