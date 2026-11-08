import { Component } from "preact";
import { useState, useEffect } from "preact/hooks";
import type { ComponentChildren } from "preact";
import { loadSettings } from "./storage";
import { streamAnalyse } from "./sse";
import type { Settings, AnalyseRequest, StreamCard, CardState, AnalyseResult } from "./types";
import { CostCard } from "./components/CostCard";
import { StatutoryRights } from "./components/StatutoryRights";
import { TermsAccordion } from "./components/TermsAccordion";
import { CompanyCard } from "./components/CompanyCard";
import { FirstRunForm } from "./components/FirstRunForm";
import { hasEvidence } from "./components/Evidence";
import { CostModelError, lifetimeCost, type Horizon } from "./cost/lifetimeCost";
import { SERVER_URL } from "./config";

const REQ_MODULES = import.meta.glob("../../fixtures/requests/*.json", { eager: true });
const FIXTURE_REQUESTS: Record<string, AnalyseRequest> = {};
for (const [path, mod] of Object.entries(REQ_MODULES)) {
  const name = path.split("/").pop()?.replace(".json", "") ?? path;
  FIXTURE_REQUESTS[name] = (mod as { default?: AnalyseRequest }).default ?? (mod as unknown as AnalyseRequest);
}

const DEFAULT_SERVER = SERVER_URL;

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
  componentDidCatch() { this.setState({ caught: true }); }
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
      const seen = (() => { try { return !!localStorage.getItem("smallprint_seen"); } catch { return true; } })();
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
        setCards((prev: CardData) => {
          if (card.card === "item") return { ...prev, item: { payload: card.payload as Partial<AnalyseResult["item"]>, state: card.state } };
          if (card.card === "cost") return { ...prev, cost: { payload: card.payload as { cost_streams: AnalyseResult["cost_streams"] }, state: card.state } };
          if (card.card === "price_drift") return { ...prev, price_drift: { payload: card.payload as AnalyseResult["price_drift"], state: card.state } };
          if (card.card === "lock_in") return { ...prev, lock_in: { payload: card.payload as AnalyseResult["lock_in"], state: card.state } };
          if (card.card === "small_print") return { ...prev, small_print: { payload: card.payload as AnalyseResult["small_print"], state: card.state } };
          if (card.card === "company") return { ...prev, company: { payload: card.payload as AnalyseResult["company"], state: card.state } };
          return prev;
        });
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

  // Compute hero stats from available card data
  const costStreams = cards.cost?.payload?.cost_streams ?? [];
  const verified = costStreams.filter((s) => hasEvidence(s.evidence?.quote, s.evidence?.url));
  let heroStats: {
    total: string;
    ringPct: number;
    ringLabel: string;
    multiplier: string | null;
    addedAtCheckout: string | null;
    recordsCount: number;
    isEstimated: boolean;
    oneOffTotal: number;
  } | null = null;

  if (verified.length > 0 && cards.cost) {
    try {
      const result = lifetimeCost(verified, settings.horizon as Horizon);
      if (result.total) {
        const total = result.total.mid;
        const oneOffTotal = verified
          .filter((s) => s.type === "one_off")
          .reduce((sum, s) => sum + (s.amount ?? 0), 0);
        const recurringTotal = total - oneOffTotal;
        const addedTotal = (cards.price_drift?.payload?.added ?? []).reduce((s, a) => s + a.amount, 0);
        heroStats = {
          total: `£${total.toFixed(2)}`,
          ringPct: total > 0 ? Math.round(recurringTotal / total * 100) : 0,
          ringLabel: cards.lock_in?.payload?.proprietary_refills ? "refills" : "ongoing",
          multiplier: oneOffTotal > 0 ? `${Math.round(total / oneOffTotal * 10) / 10}×` : null,
          addedAtCheckout: addedTotal > 0 ? `+£${addedTotal.toFixed(2)}` : null,
          recordsCount: cards.company?.payload?.records?.length ?? 0,
          isEstimated: result.state === "estimated",
          oneOffTotal,
        };
      }
    } catch (err) {
      if (!(err instanceof CostModelError)) throw err;
    }
  }

  const heroName = [
    cards.item?.payload?.name,
    purchaseTypes.length > 0 ? (purchaseTypes[0].charAt(0).toUpperCase() + purchaseTypes[0].slice(1)) : null,
    heroStats && heroStats.oneOffTotal > 0 ? `£${heroStats.oneOffTotal.toFixed(2)}` : null,
  ].filter(Boolean).join(" · ");

  const lockIn = cards.lock_in?.state === "found" || cards.lock_in?.state === "estimated"
    ? cards.lock_in.payload : null;
  const smallPrint = cards.small_print?.state === "found" || cards.small_print?.state === "estimated"
    ? (cards.small_print.payload ?? []) : [];
  const hasTerms = lockIn || smallPrint.length > 0;

  return (
    <div class="panel">
      {/* Dev harness */}
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

      {/* Panel header */}
      <header class="sp-header">
        <span class="sp-logo">SMALL<b>/</b>PRINT</span>
        <div class="sp-actions">
          <button class="btn btn--ghost-on-dark" onClick={() => setFirstRun(true)}>Settings</button>
        </div>
      </header>

      {error && <p class="error-banner">{error}</p>}

      {/* No purchase */}
      {noPurchase && (
        <div class="sp-body">
          <p class="empty-state">No purchase detected on this page — try a product, subscription or checkout page.</p>
        </div>
      )}

      {/* Results */}
      {!noPurchase && (
        <>
          {/* Hero */}
          {heroStats ? (
            <div class="sp-hero">
              {heroName && <span class="sp-hero__name">{heroName}</span>}
              <div class="sp-hero__row">
                {heroStats.ringPct > 0 && (
                  <div class="sp-ring" style={`--ring-pct: ${heroStats.ringPct}%`}>
                    <div class="sp-ring__inner">
                      {heroStats.ringPct}%
                      <span class="sp-ring__sub">{heroStats.ringLabel}</span>
                    </div>
                  </div>
                )}
                <div class="sp-stats">
                  <div class="sp-stat sp-stat--white">
                    <b>{heroStats.total}</b>
                    <small>{settings.horizon}-month cost</small>
                  </div>
                  {heroStats.multiplier && (
                    <div class="sp-stat">
                      <b>{heroStats.multiplier}</b>
                      <small>the sticker price</small>
                    </div>
                  )}
                  {heroStats.addedAtCheckout && (
                    <div class="sp-stat sp-stat--red">
                      <b>{heroStats.addedAtCheckout}</b>
                      <small>added at checkout</small>
                    </div>
                  )}
                  <div class="sp-stat">
                    <b>{heroStats.recordsCount}</b>
                    <small>public records</small>
                  </div>
                </div>
              </div>
              <div class="sp-hero__sub">
                {heroStats.isEstimated ? "Estimated at typical use" : "Quoted from source"}
              </div>
            </div>
          ) : streaming ? (
            <div class="sp-hero">
              <span class="sp-hero__name" style="opacity:.45">Analysing…</span>
            </div>
          ) : null}

          {/* Body */}
          <div class="sp-body">
            {cards.cost && (
              <CardErrorBoundary name="cost">
                <CostCard
                  costStreams={cards.cost.payload.cost_streams ?? []}
                  state={cards.cost.state}
                  horizon={settings.horizon}
                  lockIn={lockIn ?? undefined}
                  priceDrift={cards.price_drift?.payload}
                />
              </CardErrorBoundary>
            )}

            {hasTerms && (
              <CardErrorBoundary name="terms">
                <TermsAccordion lockIn={lockIn} smallPrint={smallPrint} />
              </CardErrorBoundary>
            )}

            {cards.company && (
              <CardErrorBoundary name="company">
                <CompanyCard
                  company={cards.company.payload}
                  state={cards.company.state}
                  flaggedKinds={settings.recordKinds}
                  onFlag={async (correction) => {
                    try {
                      const r = await fetch(`${serverUrl}/flag/company-match`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          brand: cards.company?.payload?.brand,
                          matched_parent: cards.company?.payload?.parent,
                          ch_number: cards.company?.payload?.ch_number,
                          match_via: cards.company?.payload?.match_via,
                          page_url: cards.item?.payload?.url ?? "",
                          correction,
                        }),
                      });
                      return r.ok;
                    } catch {
                      return false;
                    }
                  }}
                />
              </CardErrorBoundary>
            )}

            {Object.keys(cards).length === 0 && !streaming && (
              <p class="empty-state">Select a fixture and click Analyse to see results stream in.</p>
            )}
          </div>

          {/* Statutory rights once results are in */}
          {!streaming && Object.keys(cards).length > 0 && !noPurchase && (
            <StatutoryRights purchaseTypes={purchaseTypes} />
          )}
        </>
      )}
    </div>
  );
}
