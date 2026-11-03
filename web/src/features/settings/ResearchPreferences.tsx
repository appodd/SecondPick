import { useEffect, useState, type FormEvent } from "react";
import { Save } from "lucide-react";

import type { SettingsPatch, UserSettings } from "../../api/types";

export interface ResearchPreferencesProps {
  settings: UserSettings;
  onSave: (patch: SettingsPatch) => void | Promise<void>;
}

export function ResearchPreferences({
  settings,
  onSave,
}: ResearchPreferencesProps) {
  const [defaultCity, setDefaultCity] = useState(settings.default_city ?? "");
  const [allowOcr, setAllowOcr] = useState(settings.allow_ocr);
  const [preferredView, setPreferredView] = useState(settings.preferred_view);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    setDefaultCity(settings.default_city ?? "");
    setAllowOcr(settings.allow_ocr);
    setPreferredView(settings.preferred_view);
  }, [settings]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaveState("saving");
    try {
      await onSave({
        default_city: defaultCity.trim() || null,
        platforms: ["xianyu"],
        allow_ocr: allowOcr,
        preferred_view: preferredView,
      });
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  }

  return (
    <form className="preferences-form" onSubmit={handleSubmit}>
      <label>
        <span>默认城市（旧工具兼容配置）</span>
        <input
          aria-label="默认城市"
          value={defaultCity}
          onChange={(event) => setDefaultCity(event.target.value)}
        />
      </label>
      <p>不代表项目交易地区偏好，也不限定监控采集地区。地区要求请在项目选购条件中明确确认。</p>

      <fieldset>
        <legend>默认平台</legend>
        <label className="checkbox-row">
          <input type="checkbox" checked disabled />
          <span>闲鱼</span>
        </label>
      </fieldset>

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={allowOcr}
          onChange={(event) => setAllowOcr(event.target.checked)}
        />
        <span>允许本地 OCR</span>
      </label>

      <label>
        <span>默认视图</span>
        <select
          value={preferredView}
          onChange={(event) =>
            setPreferredView(event.target.value as "research" | "debug")
          }
        >
          <option value="research">研究视图</option>
          <option value="debug">调试视图</option>
        </select>
      </label>

      <div className="settings-save-row">
        <button className="primary-button" type="submit" disabled={saveState === "saving"}>
          <Save aria-hidden="true" size={15} />
          {saveState === "saving" ? "保存中..." : "保存偏好"}
        </button>
        {saveState === "saved" ? <span role="status">已保存</span> : null}
        {saveState === "error" ? <span className="scoped-error" role="status">保存失败</span> : null}
      </div>
    </form>
  );
}
