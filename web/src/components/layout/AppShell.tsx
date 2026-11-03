import { useEffect, useRef, useState, type ReactNode } from "react";
import { Menu, PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { useMediaQuery } from "../../hooks/useMediaQuery";
import { ResponsiveDrawer } from "./ResponsiveDrawer";

export interface AppShellProps {
  sidebar: ReactNode;
  main: ReactNode;
  context: ReactNode;
  contextOpen?: boolean;
  navigationKey?: string;
  contextKey?: string;
  onContextOpenChange?: (open: boolean) => void;
}

export function AppShell({
  sidebar,
  main,
  context,
  contextOpen,
  navigationKey,
  contextKey,
  onContextOpenChange,
}: AppShellProps) {
  const isDesktop = useMediaQuery("(min-width: 1180px)", true);
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [taskRailOpen, setTaskRailOpen] = useState(true);
  const [navigationDrawerOpen, setNavigationDrawerOpen] = useState(false);
  const previousNavigationKey = useRef(navigationKey);
  const mainRef = useRef<HTMLElement>(null);
  const showPersistentSidebar = isDesktop || (!isMobile && taskRailOpen);

  useEffect(() => {
    if (previousNavigationKey.current !== navigationKey) {
      if (previousNavigationKey.current?.split("?")[0] !== navigationKey?.split("?")[0] && mainRef.current) {
        mainRef.current.scrollTop = 0;
      }
      setNavigationDrawerOpen(false);
      previousNavigationKey.current = navigationKey;
    }
  }, [navigationKey]);

  return (
    <div
      className="app-shell"
      data-layout={isDesktop ? "desktop" : isMobile ? "mobile" : "tablet"}
      data-task-rail={showPersistentSidebar ? "open" : "closed"}
    >
      {showPersistentSidebar ? (
        <nav className="app-shell__sidebar" aria-label="研究任务">
          {sidebar}
        </nav>
      ) : null}
      <main ref={mainRef} className="app-shell__main">
        {!isDesktop ? (
          <div className="app-shell__toolbar">
            {isMobile ? (
              <ResponsiveDrawer
                triggerLabel="查看任务"
                title="研究任务"
                side="left"
                triggerIcon={<Menu aria-hidden="true" size={18} />}
                open={navigationDrawerOpen}
                onOpenChange={setNavigationDrawerOpen}
              >
                <nav aria-label="研究任务">{sidebar}</nav>
              </ResponsiveDrawer>
            ) : (
              <button
                className="icon-button"
                type="button"
                aria-label={taskRailOpen ? "收起任务导航" : "展开任务导航"}
                title={taskRailOpen ? "收起任务导航" : "展开任务导航"}
                onClick={() => setTaskRailOpen((current) => !current)}
              >
                {taskRailOpen ? (
                  <PanelLeftClose aria-hidden="true" size={18} />
                ) : (
                  <PanelLeftOpen aria-hidden="true" size={18} />
                )}
              </button>
            )}
            <ResponsiveDrawer
              triggerLabel="查看证据"
              title="上下文检查器"
              open={contextOpen}
              onOpenChange={onContextOpenChange}
            >
              <aside aria-label="上下文检查器">{context}</aside>
            </ResponsiveDrawer>
          </div>
        ) : null}
        <div className="app-shell__workspace">{main}</div>
      </main>
      {isDesktop ? (
        <aside key={contextKey} className="app-shell__context" aria-label="上下文检查器">
          {context}
        </aside>
      ) : null}
    </div>
  );
}
