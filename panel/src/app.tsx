import { Component } from "preact";
import { useState, useEffect } from "preact/hooks";
import type { ComponentChildren } from "preact";
import { loadSettings } from "./storage";
import { streamAnalyse } from "./sse";
import type { Settings, AnalyseRequest, StreamCard, CardState, AnalyseResult } from "./types";
import { ItemCard } from "./components/ItemCard";
import { CostCard } from "./components/CostCard";
import { PriceDriftCard } from "./components/PriceDriftCard";
import { LockInCard } from "./components/LockInCard";
import { SmallPrintCard } from "./components/SmallPrintCard";
import { CompanyCard } from "./components/CompanyCard";
import { FirstRunForm } from "./components/FirstRunForm";

// Dev harness: load request fixture files at build time
const REQ_MODULES = import.meta.glob("../../fixtures/requests/*.json", { eager: true });
const FIXTURE_REQUESTS: Record<string, AnalyseRequest> = {};
for (const [path, mod] of Object.entries(REQ_MODULES)) {
  const name = path.split("/").pop()?.replace(".json", "") ?? path;
  FIXTURE_REQUESTS[name] = (mod as { default?: AnalyseRequest }).default ?? (mod as unknown as AnalyseRequest);
}

const DEFAULT_SERVER = "http://localhost:8000";

type CardData = {
  item?: { payload: Partial<AnalyseResult["item"]>; state: CardState };
  cost?: { payload: { cost_streams: AnalyseResult["cost_streams"] }; state: CardState };
  price_drift?: { payload: AnalyseResult["price_drift"]; state: CardState };
  lock_in?: { payload: AnalyseResult["lock_in"]; state: CardState };
  small_print?: { payload: AnalyseResult["small_print"]; state: CardState };
  company?: { payload: AnalyseResult["company"]; state: CardState };
};

class CardErrorBoundary extends Component<{ name: string; children: ComponentChildren }, { caught: boolean }> {
  state = { caught: false };
  componentDidCatch() {
    this.setState({ caught: true });
  }
  render() {
    if (this.state.caught) {
      return <div class="card card--error"><p>Not found ({this.props.name})</p></div>;
    }
    return <>{this.props.children}</>;
  }
}

export function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [firstRun, setFirstRun] = useState(false);
  const [serverUrl, setServerUrl] = useState(DEFAULT_SERVER);
  const [selectedFixture, setSelectedFixture] = useState(Object.keys(FIXTURE_REQUESTS)[0] ?? "");
  const [cards, setCards] = useState<CardData>({});
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [purchaseTypes, setPurchaseTypes] = useState<string[]>([]);

  useEffect(() => {
    loadSettings().then((s) => {
      setSettings(s);
      const seen = (() => {
        try { return !!localStorage.getItem("smallprint_seen"); }
        catch { return true; }
      })();
      if (!seen) setFirstRun(true);
    });
  }, []);

  function handleSettingsComplete(s: Settings) {
    try { localStorage.setItem("smallprint_seen", "1"); } catch { /* ignore */ }
    setSettings(s);
    setFirstRun(false);
  }

  async function handleAnalyse() {
    const request = FIXTURE_REQUESTS[selectedFixture];
    if (!request) return;
    setCards({});
    setError(null);
    setStreaming(true);
    setPurchaseTypes(request.purchase_type_signals ?? []);

    try {
      for await (const event of streamAnalyse(serverUrl, request)) {
        if (event === "done") break;
        const card = event as StreamCard;
        if (card.card === "item") {
          setCards((prev: CardData) => ({ ...prev, item: { payload: card.payload as Partial<AnalyseResult["item"]>, state: card.state } }));
        } else if (card.card === "cost") {
          setCards((prev: CardData) => ({
            ...prev,
            cost: { payload: card.payload as { cost_streams: AnalyseResult["cost_streams"] }, state: card.state },
          }));
        } else if (card.card === "price_drift") {
          setCards((prev: CardData) => ({ ...prev, price_drift: { payload: card.payload as AnalyseResult["price_drift"], state: card.state } }));
        } else if (card.card === "lock_in") {
          setCards((prev: CardData) => ({ ...prev, lock_in: { payload: card.payload as AnalyseResult["lock_in"], state: card.state } }));
        } else if (card.card === "small_print") {
          setCards((prev: CardData) => ({ ...prev, small_print: { payload: card.payload as AnalyseResult["small_print"], state: card.state } }));
        } else if (card.card === "company") {
          setCards((prev: CardData) => ({ ...prev, company: { payload: card.payload as AnalyseResult["company"], state: card.state } }));
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStreaming(false);
    }
  }

  if (firstRun) return <FirstRunForm onComplete={handleSettingsComplete} />;
  if (!settings) return <div class="loading">Loading…</div>;

  const noPurchase = cards.item?.state === "n_a";

  return (
    <div class="panel">
      <div class="dev-harness">
        <label class="harness-label">
          Fixture:
          <select value={selectedFixture} onChange={(e) => setSelectedFixture((e.target as HTMLSelectElement).value)}>
            {Object.keys(FIXTURE_REQUESTS).map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </label>
        <label class="harness-label">
          Server:
          <input
            type="text"
            class="text-input text-input--small"
            value={serverUrl}
            onInput={(e) => setServerUrl((e.target as HTMLInputElement).value)}
          />
        </label>
        <button class="btn btn--primary" onClick={handleAnalyse} disabled={streaming}>
          {streaming ? "Streaming…" : "Analyse"}
        </button>
        <button class="btn btn--ghost" onClick={() => setFirstRun(true)}>Settings</button>
      </div>

      {error && <p class="error-banner">{error}</p>}

      <div class="cards">
        {noPurchase && (
          <ItemCard item={{}} state="n_a" purchaseTypes={[]} />
        )}

        {!noPurchase && (
          <>
            {cards.item && (
              <CardErrorBoundary name="item">
                <ItemCard item={cards.item.payload} state={cards.item.state} purchaseTypes={purchaseTypes} />
              </CardErrorBoundary>
            )}
            {cards.cost && (
              <CardErrorBoundary name="cost">
                <CostCard costStreams={cards.cost.payload.cost_streams ?? []} state={cards.cost.state} horizon={settings.horizon} />
              </CardErrorBoundary>
            )}
            {cards.price_drift && (
              <CardErrorBoundary name="price_drift">
                <PriceDriftCard priceDrift={cards.price_drift.payload} state={cards.price_drift.state} />
              </CardErrorBoundary>
            )}
            {cards.lock_in && (
              <CardErrorBoundary name="lock_in">
                <LockInCard lockIn={cards.lock_in.payload} state={cards.lock_in.state} />
              </CardErrorBoundary>
            )}
            {cards.small_print && (
              <CardErrorBoundary name="small_print">
                <SmallPrintCard items={cards.small_print.payload ?? []} state={cards.small_print.state} />
              </CardErrorBoundary>
            )}
            {cards.company && (
              <CardErrorBoundary name="company">
                <CompanyCard company={cards.company.payload} state={cards.company.state} flaggedKinds={settings.recordKinds} />
              </CardErrorBoundary>
            )}
          </>
        )}

        {Object.keys(cards).length === 0 && !streaming && (
          <p class="empty-state">Select a fixture and click Analyse to see results stream in.</p>
        )}
      </div>
    </div>
  );
}
