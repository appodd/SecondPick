import { Database, Info, LockKeyhole, SlidersHorizontal, Unplug } from "lucide-react";

import type { SettingsPatch, SetupStatus, UserSettings } from "../../api/types";
import { ConnectionSettings } from "./ConnectionSettings";
import { ResearchPreferences } from "./ResearchPreferences";

export interface SettingsWorkspaceProps {
  setup: SetupStatus;
  settings: UserSettings;
  onCheckEnvironment: () => void | Promise<void>;
  onCheckCodex: () => void | Promise<void>;
  onSaveSettings: (patch: SettingsPatch) => void | Promise<void>;
}

export function SettingsWorkspace({
  setup,
  settings,
  onCheckEnvironment,
  onCheckCodex,
  onSaveSettings,
}: SettingsWorkspaceProps) {
  const databasePath = setup.environment.find((check) => check.name === "database")?.detail ?? "由本地配置管理";

  return (
    <section className="settings-workspace" aria-labelledby="settings-title">
      <header className="settings-workspace__header">
        <p className="workspace-eyebrow">本地工作台</p>
        <h1 id="settings-title">设置</h1>
        <p>管理非敏感偏好并检查本地连接状态。</p>
      </header>

      <section className="settings-section" aria-labelledby="connection-settings-title">
        <div className="settings-section__title"><Unplug aria-hidden="true" size={18} /><h2 id="connection-settings-title">连接与环境</h2></div>
        <ConnectionSettings setup={setup} onCheckEnvironment={onCheckEnvironment} onCheckCodex={onCheckCodex} />
      </section>

      <section className="settings-section" aria-labelledby="research-settings-title">
        <div className="settings-section__title"><SlidersHorizontal aria-hidden="true" size={18} /><h2 id="research-settings-title">研究偏好</h2></div>
        <ResearchPreferences settings={settings} onSave={onSaveSettings} />
      </section>

      <section className="settings-section" aria-labelledby="storage-settings-title">
        <div className="settings-section__title"><Database aria-hidden="true" size={18} /><h2 id="storage-settings-title">数据与存储</h2></div>
        <dl className="settings-facts settings-facts--paths">
          <div><dt>数据库路径</dt><dd><output>{databasePath}</output></dd></div>
          <div><dt>浏览器资料</dt><dd><output>data/browser-profile/（本机保存）</output></dd></div>
          <div><dt>报告目录</dt><dd><output>data/reports/（只读）</output></dd></div>
          <div><dt>媒体与截图</dt><dd><output>data/media/、data/screenshots/（本机保存）</output></dd></div>
        </dl>
      </section>

      <section className="settings-section" aria-labelledby="privacy-settings-title">
        <div className="settings-section__title"><LockKeyhole aria-hidden="true" size={18} /><h2 id="privacy-settings-title">安全与隐私</h2></div>
        <p>Codex 凭据由 CLI 管理；闲鱼会话保存在本地浏览器资料目录。工作台不读取或展示凭据、Cookie 内容。</p>
      </section>

      <section className="settings-section" aria-labelledby="about-settings-title">
        <div className="settings-section__title"><Info aria-hidden="true" size={18} /><h2 id="about-settings-title">关于</h2></div>
        <p>本地研究工作台。Codex 按需分析已有证据；登录验证后，可明确执行搜索和商品详情采集。图片下载与 OCR 尚未接入。</p>
      </section>
    </section>
  );
}
