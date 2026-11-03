import { Archive, Plus, Settings } from "lucide-react";
import { NavLink } from "react-router-dom";

export interface TaskSummary {
  id: string;
  title: string;
  status: string;
}

export interface TaskGroup {
  label: string;
  tasks: TaskSummary[];
}

export interface TaskSidebarProps {
  groups: TaskGroup[];
}

export function TaskSidebar({ groups }: TaskSidebarProps) {
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
        {groups.map((group) => (
          <section className="task-group" key={group.label}>
            <h2>{group.label}</h2>
            <ul>
              {group.tasks.map((task) => (
                <li key={task.id}>
                  <NavLink
                    className={({ isActive }) =>
                      isActive ? "task-link task-link--active" : "task-link"
                    }
                    to={`/tasks/${task.id}`}
                  >
                    <span className="task-link__title">{task.title}</span>
                    <span className="task-link__status">{task.status}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </section>
        ))}
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
