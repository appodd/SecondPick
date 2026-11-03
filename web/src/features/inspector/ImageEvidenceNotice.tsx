export type ImageProof = { id: number; evidence?: { state: string; observed: false; input_uses?: { study_id: number; goal_revision: number; input_constructed: boolean; remote_received: false; observed: false }[] } };

export function ImageEvidenceNotice({ images }: { images: ImageProof[] }) {
  if (!images.length) return null;
  const labels: Record<string,string> = {url_only:'仅有图片链接，尚未保存文件',legacy_unverified:'有历史本地文件，尚未建立校验依据',saved:'图片文件已保存并校验',failed:'图片保存失败',pending:'图片保存尚未完成，需检查原操作',unreadable:'已登记图片不可读取或校验不符'};
  return <details className="inspector-block" aria-label="图片证据状态"><summary>图片证据与模型使用</summary>
    <p>网页预览不等于 AI 已查看；附件构造不等于远端接收，图片观察也不等于实物核验。</p>
    {images.map((image,index)=><p key={image.id}>图片 {index+1}：{labels[image.evidence?.state ?? 'url_only'] ?? '图片状态待确认'}
      {image.evidence?.input_uses?.length ? <> · 附件已构造（{image.evidence.input_uses.map(use=>`研究 #${use.study_id} · 目标 v${use.goal_revision}`).join('；')}），尚未确认送达模型</> : ' · 尚未构造研究附件'}
    </p>)}
    <p>视觉观察：尚无已验证的真实记录。本阶段仅支持离线附件验收。</p>
  </details>;
}
