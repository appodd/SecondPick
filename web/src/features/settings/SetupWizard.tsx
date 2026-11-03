import { useEffect, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, X } from "lucide-react";

import type { SettingsPatch, SetupStatus, UserSettings } from "../../api/types";
import { ConnectionSettings } from "./ConnectionSettings";

export interface SetupWizardProps {
  status: SetupStatus;
  settings: UserSettings;
  onClose: () => void;
  onSaveSettings: (patch: SettingsPatch) => void | Promise<void>;
  onCheckEnvironment?: () => void | Promise<void>;
  onCheckCodex?: () => void | Promise<void>;
}

const stepLabels = ["环境", "Codex", "闲鱼", "偏好"];
const focusableSelector = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function SetupWizard({
  status,
  settings,
  onClose,
  onSaveSettings,
  onCheckEnvironment,
  onCheckCodex,
}: SetupWizardProps) {
  const [step, setStep] = useState(0);
  const [defaultCity, setDefaultCity] = useState(settings.default_city ?? "");
  const [allowOcr, setAllowOcr] = useState(settings.allow_ocr);
  const [saving, setSaving] = useState(false);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const savingRef = useRef(saving);
  onCloseRef.current = onClose;
  savingRef.current = saving;

  useEffect(() => {
    const backdrop = backdropRef.current;
    const dialog = dialogRef.current;
    if (!backdrop || !dialog) {
      return;
    }
    const activeDialog = dialog;

    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    const backgroundElements = Array.from(
      backdrop.parentElement?.children ?? [],
    ).filter(
      (element): element is HTMLElement =>
        element instanceof HTMLElement && element !== backdrop,
    );
    const backgroundState = backgroundElements.map((element) => ({
      element,
      ariaHidden: element.getAttribute("aria-hidden"),
      inert: Boolean(element.inert),
    }));

    document.body.style.overflow = "hidden";
    backgroundElements.forEach((element) => {
      element.setAttribute("aria-hidden", "true");
      element.inert = true;
    });
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !savingRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusable = Array.from(
        activeDialog.querySelectorAll<HTMLElement>(focusableSelector),
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) {
        event.preventDefault();
        activeDialog.focus();
        return;
      }

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!activeDialog.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      backgroundState.forEach(({ element, ariaHidden, inert }) => {
        if (ariaHidden === null) {
          element.removeAttribute("aria-hidden");
        } else {
          element.setAttribute("aria-hidden", ariaHidden);
        }
        element.inert = inert;
      });
      previouslyFocused?.focus();
    };
  }, []);

  async function completeSetup() {
    setSaving(true);
    setError(null);
    try {
      await onSaveSettings({
        setup_completed: true,
        default_city: defaultCity.trim() || null,
        platforms: ["xianyu"],
        allow_ocr: allowOcr,
      });
      setFinished(true);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "设置保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="setup-backdrop" ref={backdropRef}>
      <section
        className="setup-wizard"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="setup-wizard-title"
        tabIndex={-1}
      >
        <header className="setup-wizard__header">
          <div>
            <p className="workspace-eyebrow">首次设置</p>
            <h1 id="setup-wizard-title">准备本地研究工作台</h1>
          </div>
          <button
            aria-label="关闭引导"
            className="icon-button"
            disabled={saving}
            onClick={onClose}
            ref={closeButtonRef}
            title="关闭引导"
            type="button"
          >
            <X aria-hidden="true" size={18} />
          </button>
        </header>

        <ol className="setup-steps" aria-label="设置进度">
          {stepLabels.map((label, index) => (
            <li className={index === step ? "setup-step setup-step--active" : "setup-step"} key={label}>
              <span>{index + 1}</span>
              {label}
            </li>
          ))}
        </ol>

        <div className="setup-wizard__content">
          {finished ? (
            <div className="setup-finished">
              <Check aria-hidden="true" size={24} />
              <h2>设置已保存</h2>
              {!status.can_start_research ? (
                <p>可以开始对话研究；采集前请到设置中登录并验证闲鱼。</p>
              ) : null}
              <p>你仍可浏览已有研究数据</p>
            </div>
          ) : step === 0 ? (
            <div>
              <h2>环境检查</h2>
              <p className="muted">检查本地配置和数据库状态。</p>
              <ConnectionSettings
                setup={status}
                sections={["environment"]}
                onCheckEnvironment={onCheckEnvironment}
              />
            </div>
          ) : step === 1 ? (
            <div>
              <h2>Codex 可用性</h2>
              <p className="muted">仅检查 CLI 与认证状态，不启动 Codex 进程。</p>
              <ConnectionSettings setup={status} sections={["codex"]} onCheckCodex={onCheckCodex} />
            </div>
          ) : step === 2 ? (
            <div className="setup-xianyu">
              <h2>闲鱼登录</h2>
              <dl className="settings-facts">
                <div><dt>资料目录</dt><dd>{status.xianyu.profile_present ? "已存在" : "未创建"}</dd></div>
                <div><dt>认证状态</dt><dd>{status.xianyu.auth_status === "unknown" ? "尚未验证" : status.xianyu.auth_status}</dd></div>
              </dl>
              <p>完成引导后，在设置页面点击“打开闲鱼登录窗口”，完成登录并验证。</p>
            </div>
          ) : (
            <div>
              <h2>使用偏好</h2>
              <div className="preferences-form">
                <label>
                  <span>默认城市（旧工具兼容配置，不代表交易偏好）</span>
                  <input
                    aria-label="默认城市"
                    value={defaultCity}
                    onChange={(event) => setDefaultCity(event.target.value)}
                  />
                </label>
                <label className="checkbox-row">
                  <input type="checkbox" checked disabled />
                  <span>闲鱼</span>
                </label>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={allowOcr}
                    onChange={(event) => setAllowOcr(event.target.checked)}
                  />
                  <span>允许本地 OCR</span>
                </label>
              </div>
            </div>
          )}
          {error ? <p className="scoped-error" role="status">{error}</p> : null}
        </div>

        <footer className="setup-wizard__footer">
          <div>
            <strong>你仍可浏览已有研究数据</strong>
            <button className="text-button" type="button" onClick={onClose}>稍后完成</button>
          </div>
          <div className="setup-wizard__actions">
            {!finished && step > 0 ? (
              <button className="secondary-button" type="button" onClick={() => setStep(step - 1)}>
                <ChevronLeft aria-hidden="true" size={16} />
                上一步
              </button>
            ) : null}
            {finished ? (
              <button className="primary-button" type="button" onClick={onClose}>完成</button>
            ) : step < stepLabels.length - 1 ? (
              <button className="primary-button" type="button" onClick={() => setStep(step + 1)}>
                下一步
                <ChevronRight aria-hidden="true" size={16} />
              </button>
            ) : (
              <button className="primary-button" type="button" disabled={saving} onClick={completeSetup}>
                {saving ? "保存中..." : "完成设置"}
              </button>
            )}
          </div>
        </footer>
      </section>
    </div>
  );
}
