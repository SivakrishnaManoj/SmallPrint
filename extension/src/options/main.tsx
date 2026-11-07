import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import "~panel/index.css";
import "../sidepanel/sidepanel.css";
import { FirstRunForm } from "~panel/components/FirstRunForm";
import type { Settings } from "~panel/types";
import { completeSetup, isSetupDone, loadSettings } from "../settings";

function Options() {
  const [initial, setInitial] = useState<{ settings: Settings; firstRun: boolean } | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([loadSettings(), isSetupDone()]).then(([settings, done]) => setInitial({ settings, firstRun: !done }));
  }, []);

  if (!initial) return <div class="loading">Loading…</div>;
  if (saved) {
    return (
      <div class="first-run" data-testid="setup-saved">
        <h1 class="first-run__title">You're all set</h1>
        <p class="first-run__subtitle">Click the SmallPrint icon in the toolbar to open the side panel. You can close this tab.</p>
      </div>
    );
  }
  return (
    <FirstRunForm
      askPostcode={false}
      initial={initial.settings}
      title={initial.firstRun ? "Set up SmallPrint" : "SmallPrint settings"}
      onComplete={(s) => completeSetup(s).then(() => setSaved(true))}
    />
  );
}

render(<Options />, document.getElementById("app")!);
