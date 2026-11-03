import type { ListingEvidence } from "../../api/types";

const statusLabels: Record<ListingEvidence["detail_status"], string> = {
  not_captured: "尚未采集详情",
  blocked: "详情访问被阻断",
  captured: "详情已保存",
};

export function EvidenceStatus({
  status,
}: {
  status: ListingEvidence["detail_status"];
}) {
  return (
    <span className={`evidence-status evidence-status--${status}`}>
      {statusLabels[status]}
    </span>
  );
}
