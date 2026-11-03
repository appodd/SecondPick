export type ResearchTab = "conversation" | "candidates" | "comparison" | "market" | "monitor";

export interface ResearchTabsProps {
  selectedTab: ResearchTab;
  onSelectTab: (tab: ResearchTab) => void;
}

const tabs: { id: ResearchTab; label: string }[] = [
  { id: "conversation", label: "对话" },
  { id: "candidates", label: "全部候选" },
  { id: "monitor", label: "监控" },
  { id: "comparison", label: "对比" },
  { id: "market", label: "市场" },
];

export function ResearchTabs({ selectedTab, onSelectTab }: ResearchTabsProps) {
  return (
    <div className="research-tabs" role="tablist" aria-label="研究视图">
      {tabs.map((tab) => (
        <button
          aria-selected={selectedTab === tab.id}
          className={
            selectedTab === tab.id
              ? "research-tab research-tab--active"
              : "research-tab"
          }
          key={tab.id}
          onClick={() => onSelectTab(tab.id)}
          role="tab"
          type="button"
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
