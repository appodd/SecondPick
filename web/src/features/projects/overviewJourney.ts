import type { ProjectOverview } from "../../api/projectClient";

/** Presentation only. Actions navigate; this projection never schedules work. */
export function overviewJourney(data: ProjectOverview) {
  const running = data.studies.some(s => s.state === "running");
  const queued = data.studies.some(s => s.state === "queued");
  const ended = !!data.policy.completed || data.project.status === "completed";
  if (running) return { kind: "running", title: data.report ? "正在补充研究" : "正在进行首轮研究", description: data.policy.paused ? "已有任务仍在执行，后续调度已暂停。当前结果完成后可在这里查看。" : "本轮输入已经固定，新商品不会打断本轮研究。无需重复提交。", action: "查看本轮进展", view: "research", step: 2 };
  if (ended) return { kind: "completed", title: "选购项目已结束", description: "研究报告、收藏与商品证据仍可查阅。监控状态独立管理，不因结束研究而推断采集已停止。", action: "查看研究记录", view: "research", step: data.report ? 3 : 1 };
  if (data.policy.paused) return { kind: "paused", title: "研究已暂停，已有成果仍保留", description: "不会安排新的自动研究。你仍可浏览商品、核对证据；监控采集是否运行请查看监控任务。", action: "查看研究与暂停状态", view: "research", step: data.report ? 3 : data.total ? 1 : 0 };
  if (queued) return { kind: "queued", title: "研究已排队", description: "等待服务端执行，不需要重复提交。可以先查看已收集的商品。", action: "查看排队任务", view: "research", step: 2 };
  if (data.studies[0]?.state === "failed") return { kind: "attention", title: "上次研究未完成", description: "已有报告与商品证据继续保留。查看失败原因后再决定下一步，不会自动重试。", action: "查看失败原因", view: "research", step: data.report ? 3 : 2 };
  if (data.report && (data.report.evidence_current === false || data.goal_context?.report_current === false)) return { kind: "attention", title: "有变化需要重新核对", description: "下方保留的是已保存的判断，不能视为新证据或新目标下的最新建议。", action: "查看变化与研究记录", view: "research", step: 3 };
  if (data.report) return { kind: "ready", title: "先看候选，再核对关键问题", description: "报告是一份有范围的研究判断。打开商品查看证据，或带着具体问题继续询问 Agent。", action: "比较候选商品", view: "shortlist", step: 3 };
  if (!data.total) return { kind: "empty", title: "从一小批真实商品开始", description: "选购目标已经保存。下一步设置搜索词与采集范围；创建项目本身不会启动采集。", action: "设置监控计划", view: "monitors", step: 0 };
  return { kind: "collecting", title: data.eligible < data.policy.minimum ? "正在积累可比较的样本" : "样本已积累，等待首轮研究", description: `${data.eligible} / ${data.policy.minimum} 件初步可比较样本。${data.policy.auto_research ? "是否已安排研究以任务状态为准。" : "自动研究未开启，可在 Agent 研究中选择有限样本。"}初筛符合不代表已经核验。`, action: data.eligible < data.policy.minimum ? "查看监控与采集" : "查看首轮研究", view: data.eligible < data.policy.minimum ? "monitors" : "research", step: 1 };
}
