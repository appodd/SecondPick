import type { ProjectOverview, Report } from "../../api/projectClient";
import { evidenceText } from "../inspector/evidencePresentation";

export function reportCandidateIds(report: Report | null): number[] | null {
  if (!report) return [];
  try {
    const ids: unknown = JSON.parse(report.candidate_ids_json);
    return Array.isArray(ids) && ids.every(id => Number.isSafeInteger(id) && id > 0) ? [...new Set(ids as number[])] : null;
  } catch { return null; }
}

/** A labeled, verbatim opening is useful when a report has no conclusion section.
 * Preserve its entire scope/qualifiers. Never promote a later product paragraph
 * or a truncated sentence into an overall recommendation. */
export function reportOpening(content: string): string | null {
  const opening = content.trim().split(/\n\s*\n/)[0]?.trim() ?? "";
  return opening && opening.length <= 500 && !/^[#>*\-]|^\d+[.、]|https?:\/\//.test(opening) ? opening : null;
}

/** Verbatim complete sentence from an explicit conclusion section, or a narrowly marked introduction.
 * No character truncation, inferred recommendation, or scanning later product-specific paragraphs. */
export function reportConclusion(content: string): string | null {
  const paragraphs = content.trim().split(/\n\s*\n/);
  const heading = /^(?:#{1,6}\s*)?(?:一句话结论|综合结论|综合判断|当前结论|选购结论)(?:\s*[：:]\s*(.*)|\s*)$/;
  for (let i = 0; i < paragraphs.length; i++) {
    const block = paragraphs[i].trim();
    const firstLine = block.split("\n")[0].trim().replace(/\*\*/g, "");
    const match = firstLine.match(heading);
    if (!match) continue;
    const text = match[1] || block.split("\n").slice(1).join(" ") || paragraphs[i + 1] || "";
    const sentence = text.trim().match(/^[^。！？\n]+[。！？]/)?.[0];
    if (sentence && sentence.length <= 160 && !/^[#>*\-]|https?:\/\//.test(sentence)) return sentence;
  }
  const intro = paragraphs[0] ?? "";
  if (/^[#>*\-]|^\d+[.、]/.test(intro)) return null;
  // An explicit opening recommendation may name several candidates. Keep the
  // complete sentence, with its qualifications; never synthesize a shorter one.
  const explicit = intro.match(/^(?:当前建议保持|当前选购建议|本轮选购建议)[：:]\s*[^。！？\n]+[。！？]/)?.[0];
  if (explicit && explicit.length <= 280 && !/https?:\/\/|如果|假设|例如|示例/.test(explicit)) return explicit;
  const sentences = intro.match(/[^。！？\n]+[。！？]/g) ?? [];
  return sentences.find(sentence => sentence.length <= 160
    && /^(?:现有证据|当前证据|综合来看|综合判断|总体来看|目前建议|当前建议|本轮建议|本次建议)/.test(sentence.trim())
    && /核实|建议|购买|下单|观望|证据不足|暂不|优先/.test(sentence)
    && !/[#＃]|如果|假设|例如|示例|[“”「」]/.test(sentence))?.trim() ?? null;
}

export function overviewReport(data: ProjectOverview) {
  const report = data.report;
  const ids = reportCandidateIds(report);
  // Selected questions and seller studies must never replace the current report's evidence.
  const study = report ? data.studies.find(value => value.state === "completed" && ["initial", "incremental", "integration"].includes(value.kind)
    && (report.study_id !== undefined ? value.id === report.study_id : value.snapshot_at === report.snapshot_at && value.result?.content === report.content)) : undefined;
  const research = study?.result?.research;
  const candidates = (ids ?? []).slice(0, 3).map(id => ({ id, card: data.cards.find(card => card.listing_id === id),
    assessment: research?.assessments.find(item => item.listing_id === id) }));
  const relevant = ids === null ? [] : research?.assessments.filter(item => ids.length ? ids.includes(item.listing_id) : true) ?? [];
  const concerns = relevant.flatMap(item => item.judgments.filter(judgment => judgment.status !== "MET" && evidenceText(judgment.reason)).map(judgment => ({
    listingId: item.listing_id, ...judgment, criterion: research?.criteria.find(criterion => criterion.criterion_id === judgment.criterion_id),
  }))).sort((a, b) => (a.status === "UNKNOWN" ? (a.criterion?.priority === "hard" ? 1 : 2) : 0)
    - (b.status === "UNKNOWN" ? (b.criterion?.priority === "hard" ? 1 : 2) : 0));
  // Important exceptions first; at the same priority, show different requirements before repeats.
  const priority = concerns.filter(item => item.status !== "UNKNOWN");
  function varied(items: typeof concerns) {
    const seen = new Set<string>();
    const first: typeof concerns = [], remaining: typeof concerns = [];
    for (const item of items) {
      (seen.has(item.criterion_id) ? remaining : first).push(item);
      seen.add(item.criterion_id);
    }
    return [...first, ...remaining];
  }
  const unknown = [
    ...varied(concerns.filter(item => item.status === "UNKNOWN" && item.criterion?.priority === "hard")),
    ...varied(concerns.filter(item => item.status === "UNKNOWN" && item.criterion?.priority !== "hard")),
  ];
  return { ids, study, candidates, concerns: [...priority, ...unknown].slice(0, 3), conclusion: report ? reportConclusion(report.content) : null };
}
