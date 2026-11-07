import { useState } from "preact/hooks";
import { saveSettings, savePostcode } from "../storage";
import type { Settings } from "../types";
import { DEFAULT_SETTINGS } from "../types";

interface Props {
  onComplete: (settings: Settings) => void;
}

const RECORD_KIND_OPTIONS = [
  { id: "political_donations", label: "Political donations" },
  { id: "gender_pay_gap", label: "Gender pay gap" },
  { id: "regulator_decisions", label: "Regulator decisions" },
  { id: "modern_slavery", label: "Modern slavery statements" },
  { id: "b_corp", label: "B Corp certification" },
];

export function FirstRunForm({ onComplete }: Props) {
  const [horizon, setHorizon] = useState<12 | 24>(12);
  const [recordKinds, setRecordKinds] = useState<string[]>(DEFAULT_SETTINGS.recordKinds);
  const [postcode, setPostcode] = useState("");

  function toggleKind(id: string) {
    setRecordKinds((prev) =>
      prev.includes(id) ? prev.filter((k) => k !== id) : [...prev, id]
    );
  }

  async function handleSkip() {
    const settings: Settings = { ...DEFAULT_SETTINGS };
    await saveSettings(settings);
    onComplete(settings);
  }

  async function handleSave(e: Event) {
    e.preventDefault();
    const settings: Settings = { horizon, recordKinds };
    await saveSettings(settings);
    // Postcode saved locally; never sent to server
    if (postcode.trim()) {
      savePostcode(postcode.trim());
    }
    onComplete(settings);
  }

  return (
    <div class="first-run">
      <h1 class="first-run__title">Set up Small Print</h1>
      <p class="first-run__subtitle">Takes 30 seconds. You can change this any time.</p>

      <form onSubmit={handleSave} class="first-run__form">
        <fieldset>
          <legend>Default horizon for cost calculations</legend>
          <div class="toggle-group">
            <button type="button" class={horizon === 12 ? "toggle active" : "toggle"} onClick={() => setHorizon(12)}>12 months</button>
            <button type="button" class={horizon === 24 ? "toggle active" : "toggle"} onClick={() => setHorizon(24)}>24 months</button>
          </div>
        </fieldset>

        <fieldset>
          <legend>Flag company records for</legend>
          <div class="checkbox-group">
            {RECORD_KIND_OPTIONS.map((opt) => (
              <label key={opt.id} class="checkbox-label">
                <input
                  type="checkbox"
                  checked={recordKinds.includes(opt.id)}
                  onChange={() => toggleKind(opt.id)}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend>Home postcode <span class="field-note">(stays on this device, never sent to any server)</span></legend>
          <input
            type="text"
            class="text-input"
            placeholder="e.g. EH1 1YZ"
            value={postcode}
            onInput={(e) => setPostcode((e.target as HTMLInputElement).value)}
            maxLength={8}
          />
        </fieldset>

        <div class="first-run__actions">
          <button type="submit" class="btn btn--primary">Save and start</button>
          <button type="button" class="btn btn--ghost" onClick={handleSkip}>Skip (use defaults)</button>
        </div>
      </form>
    </div>
  );
}
