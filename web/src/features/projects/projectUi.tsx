import type { ReactNode } from "react";
import { Layers, Database, Bookmark, Radio, Activity } from "lucide-react";
import type { ProjectCard, ProjectDraft } from "../../api/projectClient";
import { ResponsiveDrawer } from "../../components/layout/ResponsiveDrawer";
import { ProductImage } from "./ProductImages";

export function ProductThumbnail({
  card,
  large = false,
}: {
  card: ProjectCard;
  large?: boolean;
}) {
  return <ProductImage src={card.product_images?.cover_url??card.image_url} state={card.product_images?.state} title={card.title} large={large} />;
}

export const views = [
  ["overview", "研究概览", Layers],
  ["shortlist", "候选清单", Bookmark],
  ["products", "全部商品", Database],
  ["monitors", "监控任务", Radio],
  ["research", "Agent 研究", Activity],
] as const;
export const pageDescriptions: Record<(typeof views)[number][0], string> = {
  overview: "查看当前选购结论、重要变化和下一步建议。",
  shortlist: "集中管理值得考虑的商品，查看依据并进行比较。",
  products: "浏览已采集商品，筛选、查看详情并管理商品。",
  monitors: "管理搜索与采集计划，查看运行状态、执行记录和异常。",
  research: "基于「全部商品」与当前选购目标开展研究，也可针对指定商品或问题深入分析。",
};
const labels: Record<string, string> = {
  collecting_baseline: "研究基线尚未形成",
  initial_queued: "首轮研究排队中",
  initial_running: "首轮研究阶段",
  incremental: "增量研究阶段",
  paused: "研究已暂停",
  blocked: "研究受阻",
  completed: "项目已完成",
  waiting: "等待 AI 分析",
  needs_information: "信息待补充",
  rule_excluded: "规则初筛排除",
  queued: "排队中",
  running: "运行中",
  evaluated: "已分析",
  summarized: "批次概述（无逐项评价）",
  under_ai: "已纳入研究任务（含排队）",
  failed: "失败",
  stopped: "已停止",
  needs_attention: "需要处理",
  expired: "已到期",
};
export const label = (state: string) => labels[state] ?? state;
export const date = (value?: string | null) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "暂无";
export const price = (card: ProjectCard) =>
  card.current_quote && !card.current_quote.valid ? "价格待确认" : card.price_value !== null
    ? `¥${card.price_value.toLocaleString("zh-CN")}`
    : "价格未知";
export const emptyDraft: ProjectDraft = {
  title: "",
  goal: "",
  budget: null,
  hard: [],
  soft: [],
  minimum: 20,
  auto_research: false,
  auto_cover_cache: true,
};

export function Panel({
  children,
  className = "",
  variant = "default",
}: {
  children: ReactNode;
  className?: string;
  variant?: "default" | "emphasis";
}) {
  return <section className={`sp-panel${variant === "emphasis" ? " sp-panel-emphasis" : ""} ${className}`}>{children}</section>;
}

export function Modal({
  title,
  children,
  close,
  bodyTitle = true,
  footer,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  bodyTitle?: boolean;
  footer?: ReactNode;
}) {
  return (
    <ResponsiveDrawer
      title={title}
      triggerLabel={title}
      open
      footer={footer ? <div className="sp-form sp-modal-footer">{footer}</div> : undefined}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <div className="sp-form">
        {bodyTitle ? <h2>{title}</h2> : null}
        {children}
      </div>
    </ResponsiveDrawer>
  );
}
