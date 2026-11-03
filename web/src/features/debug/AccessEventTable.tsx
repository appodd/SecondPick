import type { GlobalPlatformAccessEvents } from "../../api/types";

export function AccessEventTable({ data }: { data: GlobalPlatformAccessEvents }) {
  return (
    <section className="debug-section" aria-labelledby="access-events-title">
      <h2 id="access-events-title">平台访问事件</h2>
      <p className="scope-warning" role="note">{data.warning}</p>
      {data.events.length === 0 ? (
        <p className="muted">暂无平台访问事件。</p>
      ) : (
        <div className="data-table-scroll">
          <table className="data-table debug-event-table">
            <thead><tr><th>ID</th><th>平台</th><th>操作</th><th>目标</th><th>时间</th></tr></thead>
            <tbody>
              {data.events.map((event) => (
                <tr key={event.id}>
                  <td>#{event.id}</td>
                  <td>{event.platform}</td>
                  <td>{event.operation}</td>
                  <td>{event.target ?? "—"}</td>
                  <td>{event.attempted_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
