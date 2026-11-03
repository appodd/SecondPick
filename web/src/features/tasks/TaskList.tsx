import { Archive, Plus, Settings } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";

import type { TaskListItem } from "../../api/types";

export interface TaskListProps {
  tasks: TaskListItem[];
  isLoading?: boolean;
  isLoadingMore?: boolean;
  error?: Error | null;
  totalCount?: number;
  returnedCount?: number;
  truncated?: boolean;
  onLoadMore?: () => void | Promise<void>;
}

function hrefForTask(taskId: number, search: string) {
  const current = new URLSearchParams(search);
  const next = new URLSearchParams();

  for (const key of ["tab", "view"]) {
    const value = current.get(key);
    if (value) {
      next.set(key, value);
    }
  }

  const query = next.toString();
  return query ? `/tasks/${taskId}?${query}` : `/tasks/${taskId}`;
}

const statusLabels: Record<string, string> = {
  queued: "排队中", running: "分析中", waiting_confirmation: "待确认", completed: "分析完成",
  failed: "分析失败", cancelled: "已停止", interrupted: "已中断",
  idle: "空闲",
  collecting: "采集中",
  ready: "就绪",
  blocked: "已阻断",
  cooldown: "冷却中",
  active: "进行中",
};

function statusLabel(status: string) {
  return statusLabels[status] ?? status;
}

export function TaskList({
  tasks,
  isLoading,
  isLoadingMore,
  error,
  totalCount = tasks.length,
  returnedCount = tasks.length,
  truncated = false,
  onLoadMore,
}: TaskListProps) {
  const location = useLocation();

  return (
    <div className="task-sidebar">
      <div className="task-sidebar__header">
        <div className="product-title">
          <Archive aria-hidden="true" size={18} strokeWidth={1.8} />
          <span>本地研究工作台</span>
        </div>
        <NavLink
          className="new-research-button"
          to="/new"
        >
          <Plus aria-hidden="true" size={17} />
          新研究
        </NavLink>
      </div>

      <div className="task-groups" aria-label="任务列表">
        {isLoading ? <p className="task-list-state">加载任务...</p> : null}
        {error ? (
          <p className="task-list-state task-list-state--error">
            任务列表加载失败
          </p>
        ) : null}
        {!isLoading && !error && tasks.length === 0 ? (
          <p className="task-list-state">暂无研究任务</p>
        ) : null}
        {tasks.length > 0 ? (
          <section className="task-group">
            <h2>最近</h2>
            <ul>
              {tasks.map((task) => (
                <li key={task.id}>
                  <NavLink
                    className={({ isActive }) =>
                      isActive ? "task-link task-link--active" : "task-link"
                    }
                    to={hrefForTask(task.id, location.search)}
                  >
                    <span className="task-link__title">{task.title}</span>
                    <span className="task-link__status">
                      {task.city} · {statusLabel(task.operation_state ?? task.status)}
                    </span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        {!isLoading && !error && totalCount > 0 ? (
          <div className="task-history-pagination">
            <span>显示 {returnedCount} / {totalCount} 个任务</span>
            {truncated && onLoadMore ? (
              <button
                type="button"
                disabled={isLoadingMore}
                onClick={() => onLoadMore()}
              >
                {isLoadingMore ? "加载中..." : "加载更多任务"}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <NavLink
        className={({ isActive }) =>
          isActive ? "settings-link active" : "settings-link"
        }
        to="/settings"
      >
        <Settings aria-hidden="true" size={17} />
        设置
      </NavLink>
    </div>
  );
}
