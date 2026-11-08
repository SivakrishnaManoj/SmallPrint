import { useState } from "preact/hooks";
import { saveSettings } from "../storage";
import type { Settings } from "../types";
import { DEFAULT_SETTINGS } from "../types";

interface Props {
  onComplete: (settings: Settings) => void;
  initial?: Settings;
  title?: string;
}

const TILES = [
  { id: "donation", label: "Political donations", source: "Electoral Commission" },
  { id: "gender_pay_gap", label: "Gender pay gap", source: "GOV.UK" },
  { id: "modern_slavery", label: "Modern slavery", source: "GOV.UK registry" },
  { id: "asa_ruling", label: "Advertising rulings", source: "ASA" },
];

export function FirstRunForm({ onComplete, initial = DEFAULT_SETTINGS, title }: Props) {
  const [horizon, setHorizon] = useState<12 | 24>(initial.horizon);
  const [recordKinds, setRecordKinds] = useState<string[]>(initial.recordKinds);

  const isSetup = !title || title.toLowerCase().includes("set up");

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
    const settings: Settings = {
      horizon,
      recordKinds: recordKinds.filter((k) => k !== "asa_ruling"),
    };
    await saveSettings(settings);
    onComplete(settings);
  }

  return (
    <div class="fr-panel">
      <div class="fr-header">
        <span class="sp-logo">SMALL<b>/</b>PRINT</span>
        <small>{isSetup ? "Setup" : "Settings"}</small>
      </div>
      <div class="fr-body">
        <form onSubmit={handleSave}>
          {isSetup && (
            <>
              <h1 class="fr-headline">The price is only the <em>first</em> number.</h1>
              <p class="fr-sub">See lifetime cost, lock-in terms and who owns the brand, quoted from the source.</p>
            </>
          )}

          <p class="fr-q">Flag these public records</p>
          <div class="fr-tiles">
            {TILES.map((tile) => {
              const on = recordKinds.includes(tile.id);
              return (
                <button
                  key={tile.id}
                  type="button"
                  class={on ? "fr-tile fr-tile--on" : "fr-tile"}
                  onClick={() => toggleKind(tile.id)}
                >
                  <div class="fr-tile__ic" />
                  {tile.label}
                  <small>{tile.source}</small>
                </button>
              );
            })}
          </div>

          <p class="fr-q">Show costs over</p>
          <div class="fr-track">
            <input
              type="range"
              min="12"
              max="24"
              step="12"
              value={horizon}
              class="fr-slider"
              onInput={(e) => setHorizon(Number((e.target as HTMLInputElement).value) as 12 | 24)}
            />
          </div>
          <div class="fr-track-labels">
            {horizon === 12 ? <b>12 months</b> : <span>12 months</span>}
            {horizon === 24 ? <b>24 months</b> : <span>24 months</span>}
          </div>

          <div class="fr-privacy">
            <span>🔒</span>
            <span>Saved only in this browser. Read-only: we never click, buy or fill in forms.</span>
          </div>

          <button type="submit" class="fr-btn-primary">
            {isSetup ? "Start using Small Print" : "Save settings"}
          </button>
          <button type="button" class="fr-btn-ghost" onClick={handleSkip}>
            {isSetup ? "Skip, use defaults" : "Cancel"}
          </button>
        </form>
      </div>
    </div>
  );
}
