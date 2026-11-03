import { CheckCircle2, CircleAlert, RefreshCw } from "lucide-react";

import type { SetupStatus } from "../../api/types";
import { XianyuConnection } from "./XianyuConnection";

export interface ConnectionSettingsProps {
  setup: SetupStatus;
  sections?: Array<"environment" | "codex" | "xianyu">;
  checkingEnvironment?: boolean;
  checkingCodex?: boolean;
  onCheckEnvironment?: () => void | Promise<void>;
  onCheckCodex?: () => void | Promise<void>;
}

function statusText(ok: boolean, success: string, failure: string) {
  return ok ? success : failure;
}

export function ConnectionSettings({
  setup,
  sections = ["environment", "codex", "xianyu"],
  checkingEnvironment = false,
  checkingCodex = false,
  onCheckEnvironment,
  onCheckCodex,
}: ConnectionSettingsProps) {
  return (
    <div className="connection-settings">
      {sections.includes("environment") ? <div className="settings-subsection">
        <div className="settings-subsection__heading">
          <div>
            <h3>本地环境</h3>
            <p>检查配置与本地数据库，不启动浏览器。</p>
          </div>
          {onCheckEnvironment ? (
            <button
              className="secondary-button"
              type="button"
              disabled={checkingEnvironment}
              onClick={onCheckEnvironment}
            >
              <RefreshCw aria-hidden="true" size={15} />
              {checkingEnvironment ? "检查中..." : "重新检查"}
            </button>
          ) : null}
        </div>
        <ul className="status-list">
          {setup.environment.map((check) => (
            <li key={check.name}>
              {check.ok ? (
                <CheckCircle2 aria-hidden="true" size={16} />
              ) : (
                <CircleAlert aria-hidden="true" size={16} />
              )}
              <span>{check.name}</span>
              <strong>{check.ok ? "可用" : "需处理"}</strong>
              <small>{check.detail}</small>
            </li>
          ))}
        </ul>
      </div> : null}

      {sections.includes("codex") ? <div className="settings-subsection">
        <div className="settings-subsection__heading">
          <div>
            <h3>Codex</h3>
            <p>研究请求发生时按需启动</p>
          </div>
          {onCheckCodex ? (
            <button
              className="secondary-button"
              type="button"
              disabled={checkingCodex}
              onClick={onCheckCodex}
            >
              <RefreshCw aria-hidden="true" size={15} />
              {checkingCodex ? "检查中..." : "检查可用性"}
            </button>
          ) : null}
        </div>
        <dl className="settings-facts">
          <div>
            <dt>CLI</dt>
            <dd>
              {statusText(setup.codex.cli_available, "已安装", "不可用")}
            </dd>
          </div>
          <div>
            <dt>认证</dt>
            <dd>
              {statusText(setup.codex.auth_available, "可用", "需要认证")}
            </dd>
          </div>
          <div>
            <dt>运行状态</dt>
            <dd>按需启动，当前未运行</dd>
          </div>
        </dl>
      </div> : null}

      {sections.includes("xianyu") ? <div className="settings-subsection">
        <h3>闲鱼</h3>
        <dl className="settings-facts">
          <div>
            <dt>浏览器资料</dt>
            <dd>{setup.xianyu.profile_present ? "已存在" : "未创建"}</dd>
          </div>
        </dl>
        <XianyuConnection />
      </div> : null}
    </div>
  );
}
