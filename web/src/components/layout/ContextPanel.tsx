import type { ReactNode } from "react";

export interface ContextPanelProps {
  children?: ReactNode;
  title?: string;
  status?: string;
  description?: string;
}

export function ContextPanel({
  children,
  title,
  status,
  description,
}: ContextPanelProps) {
  if (children) {
    return <div className="context-panel">{children}</div>;
  }

  return (
    <div className="context-panel">
      <div className="context-panel__heading">
        <p>上下文检查器</p>
        <h2>{title ?? "上下文"}</h2>
      </div>
      <div className="context-panel__status">
        <span className="status-indicator" aria-hidden="true" />
        {status ?? "只读"}
      </div>
      {description ? <p className="context-panel__description">{description}</p> : null}
      <dl className="context-panel__facts">
        <div>
          <dt>证据模式</dt>
          <dd>只读</dd>
        </div>
        <div>
          <dt>数据来源</dt>
          <dd>本地记录</dd>
        </div>
      </dl>
    </div>
  );
}
