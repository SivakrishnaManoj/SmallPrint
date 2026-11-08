import { Component } from "preact";
import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type { AnalyseResult, Settings, StreamCard } from "~panel/types";
import { DEFAULT_SETTINGS } from "~panel/types";
import { CostCard } from "~panel/components/CostCard";
import { StatutoryRights } from "~panel/components/StatutoryRights";
import { TermsAccordion } from "~panel/components/TermsAccordion";
import { CompanyCard } from "~panel/components/CompanyCard";
import { FirstRunForm } from "~panel/components/FirstRunForm";
import { hasEvidence } from "~panel/components/Evidence";
import { CostModelError, lifetimeCost, type Horizon } from "~panel/cost/lifetimeCost";
import { CANNED_REQUEST, DEFAULT_SERVER_URL, TIMEOUTS, type AnalyseBody } from "../config";
import { useActiveDetection } from "./activeDetection";
import { usePriceDrift } from "./priceDriftHook";
import { streamAnalyse } from "../sse";
import { fetchTermsDocuments } from "../terms/fetchTerms";
import { getInstallId } from "../install";
import { completeSetup, isSetupDone, loadSettings, onSettingsChanged } from "../settings";
import { loadServerUrl, saveServerUrl } from "./serverUrl";

const TOTAL_CARDS = 6;

type Status = "streaming" | "done" | "error";

class CardErrorBoundary extends Component<{ name: string; children: ComponentChildren }, { caught: boolean }> {
  state = { caught: false };
  componentDidCatch(err: unknown) {
    console.error(`[smallprint] ${this.props.name} card failed to render`, err);
    this.setState({ caught: true });
  }
  render() {
    return this.state.caught
      ? <div class="card card--error"><p>Couldn't show this card ({this.props.name})</p></div>
      : <>{this.props.children}</>;
  }
}

export function App() {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [serverUrl, setServerUrl] = useState<string | null>(null);
  const [setupDone, setSetupDone] = useState<boolean | null>(null);
  const [editingSettings, setEditingSettings] = useState(false);
  const [cards, setCards] = useState<StreamCard[]>([]);
  const [status, setStatus] = useState<Status>("done");
  const [phase, setPhase] = useState<"terms" | "cards">("cards");
  const [error, setError] = useState<string | null>(null);
  const run = useRef<AbortController | null>(null);
  const [demo, setDemo] = useState(false);
  const active = useActiveDetection();
  // V3: price drift is computed in this browser (it never leaves it) and overrides the server's card.
  const [tabId, setTabId] = useState<number | null>(null);
  useEffect(() => {
    chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => setTabId(tab?.id ?? null)).catch(() => {});
  }, [active?.url]);
  const localDrift = usePriceDrift(tabId);

  const request: AnalyseBody | null = demo
    ? CANNED_REQUEST
    : active?.detection.status === "purchase" ? active.detection.request : null;
  const requestKey = request ? JSON.stringify(request) : null;
  const noPurchasePage = !demo && active !== undefined && request === null;

  useEffect(() => {
    loadSettings().then(setSettings).catch(() => {});
    isSetupDone().then(setSetupDone).catch(() => setSetupDone(false));
    loadServerUrl(DEFAULT_SERVER_URL).then(setServerUrl);
    const off = onSettingsChanged((s, done) => { setSettings(s); setSetupDone(done); });
    return () => { off(); run.current?.abort(); };
  }, []);

  useEffect(() => {
    if (serverUrl && setupDone && request) analyse(serverUrl, request, !demo);
    else if (!request) {
      run.current?.abort();
      run.current = null;
      setCards([]);
      setError(null);
      setStatus("done");
    }
  }, [serverUrl, setupDone, requestKey]);

  useEffect(() => setDemo(false), [active?.url]);

  const rerun = () => serverUrl && request && analyse(serverUrl, request, !demo);

  async function analyse(url: string, body: AnalyseBody, fetchTerms = true) {
    run.current?.abort();
    const controller = new AbortController();
    run.current = controller;
    setCards([]);
    setError(null);
    setStatus("streaming");
    try {
      const installId = await getInstallId();
      if (fetchTerms && !body.terms && body.links.length > 0) {
        setPhase("terms");
        const terms = await fetchTermsDocuments(body.links, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (terms.length > 0) body = { ...body, terms };
      }
      setPhase("cards");
      for await (const card of streamAnalyse(url, body, { ...TIMEOUTS, installId, signal: controller.signal })) {
        if (controller.signal.aborted) return;
        setCards((prev) => [...prev.filter((c) => c.card !== card.card), card]);
      }
      if (run.current === controller) setStatus("done");
    } catch (err) {
      if (run.current !== controller) return;
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    } finally {
      if (run.current === controller) setStatus((s) => (s === "streaming" ? "done" : s));
    }
  }

  function onSubmitServer(e: Event) {
    e.preventDefault();
    const input = (e.currentTarget as HTMLFormElement).elements.namedItem("server") as HTMLInputElement;
    const next = input.value.trim() || DEFAULT_SERVER_URL;
    saveServerUrl(next);
    setEditingSettings(false);
    if (next === serverUrl) rerun();
    else setServerUrl(next);
  }

  async function onSettingsDone(s: Settings) {
    await completeSetup(s);
    setSettings(s);
    setEditingSettings(false);
    setSetupDone(true);
  }

  if (setupDone === null) return <div class="loading">Loading…</div>;
  if (!setupDone || editingSettings) {
    return (
      <div class="panel" data-testid="settings-form">
        <FirstRunForm
          initial={settings}
          title={setupDone ? "Settings" : "Set up SmallPrint"}
          onComplete={onSettingsDone}
        />
        {setupDone && (
          <form class="sp-settings" onSubmit={onSubmitServer} data-testid="server-form">
            <label for="server">Server (for testing)</label>
            <input id="server" name="server" class="text-input" type="url" defaultValue={serverUrl ?? ""} placeholder={DEFAULT_SERVER_URL} />
            <button class="btn btn--ghost" type="submit">Save server</button>
          </form>
        )}
      </div>
    );
  }

  // Gather cards by name
  const itemCard = cards.find((c) => c.card === "item");
  const costCard = cards.find((c) => c.card === "cost");
  const priceDriftCard = cards.find((c) => c.card === "price_drift");
  const lockInCard = cards.find((c) => c.card === "lock_in");
  const smallPrintCard = cards.find((c) => c.card === "small_print");
  const companyCard = cards.find((c) => c.card === "company");

  const noPurchase = itemCard?.state === "n_a";
  const purchaseTypes = request?.purchase_type_signals ?? [];

  const driftPayload: AnalyseResult["price_drift"] | null =
    (localDrift as AnalyseResult["price_drift"] | null) ?? (priceDriftCard ? (priceDriftCard.payload as AnalyseResult["price_drift"]) : null);

  // v4: report a wrong company match to the backend.
  const onFlagCompany = serverUrl
    ? async (correction?: string): Promise<boolean> => {
        try {
          const installId = await getInstallId();
          const company = companyCard?.payload as AnalyseResult["company"] | undefined;
          const r = await fetch(`${serverUrl}/flag/company-match`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...(installId ? { "X-Install-Id": installId } : {}) },
            body: JSON.stringify({
              brand: company?.brand,
              matched_parent: company?.parent,
              ch_number: company?.ch_number,
              match_via: company?.match_via,
              page_url: (itemCard?.payload as Partial<AnalyseResult["item"]> | undefined)?.url ?? request?.item.url ?? "",
              correction,
            }),
          });
          return r.ok;
        } catch {
          return false;
        }
      }
    : undefined;

  const lockIn = lockInCard?.state === "found" || lockInCard?.state === "estimated"
    ? (lockInCard.payload as AnalyseResult["lock_in"]) : null;
  const smallPrint = smallPrintCard?.state === "found" || smallPrintCard?.state === "estimated"
    ? (Array.isArray(smallPrintCard.payload) ? smallPrintCard.payload as AnalyseResult["small_print"] : []) : [];

  // Compute hero stats
  const costStreams = costCard ? ((costCard.payload as { cost_streams?: AnalyseResult["cost_streams"] }).cost_streams ?? []) : [];
  const verifiedStreams = costStreams.filter((s) => hasEvidence(s.evidence?.quote, s.evidence?.url));
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

  if (verifiedStreams.length > 0 && costCard) {
    try {
      const result = lifetimeCost(verifiedStreams, settings.horizon as Horizon);
      if (result.total) {
        const total = result.total.mid;
        const oneOffTotal = verifiedStreams
          .filter((s) => s.type === "one_off")
          .reduce((sum, s) => sum + (s.amount ?? 0), 0);
        const recurringTotal = total - oneOffTotal;
        const priceDrift = driftPayload;
        const addedTotal = (priceDrift?.added ?? []).reduce((s, a) => s + a.amount, 0);
        const company = companyCard ? (companyCard.payload as AnalyseResult["company"]) : null;
        heroStats = {
          total: `£${total.toFixed(2)}`,
          ringPct: total > 0 ? Math.round(recurringTotal / total * 100) : 0,
          ringLabel: lockIn?.proprietary_refills ? "refills" : "ongoing",
          multiplier: oneOffTotal > 0 ? `${Math.round(total / oneOffTotal * 10) / 10}×` : null,
          addedAtCheckout: addedTotal > 0 ? `+£${addedTotal.toFixed(2)}` : null,
          recordsCount: company?.records?.length ?? 0,
          isEstimated: result.state === "estimated",
          oneOffTotal,
        };
      }
    } catch (err) {
      if (!(err instanceof CostModelError)) throw err;
    }
  }

  const heroName = [
    (itemCard?.payload as Partial<AnalyseResult["item"]> | undefined)?.name,
    purchaseTypes.length > 0 ? (purchaseTypes[0].charAt(0).toUpperCase() + purchaseTypes[0].slice(1)) : null,
    heroStats && heroStats.oneOffTotal > 0 ? `£${heroStats.oneOffTotal.toFixed(2)}` : null,
  ].filter(Boolean).join(" · ");

  return (
    <div class="panel">
      {/* Panel header */}
      <header class="sp-header">
        <span class="sp-logo">SMALL<b>/</b>PRINT</span>
        <div class="sp-actions">
          <button class="btn btn--ghost-on-dark" onClick={() => setEditingSettings(true)}>Settings</button>
          <button
            class="btn btn--primary"
            onClick={rerun}
            disabled={status === "streaming" || !serverUrl || !request}
          >
            Re-run
          </button>
        </div>
      </header>

      {status === "error" && (
        <div class="error-banner sp-error" role="alert">
          <span>{error}</span>
          <button class="btn btn--ghost" onClick={rerun}>Retry</button>
        </div>
      )}

      {/* No purchase — before analysis (no request) or after analysis (item = n_a) */}
      {(noPurchasePage || noPurchase) && (
        <div class="sp-body" data-testid="no-purchase">
          <p class="empty-state">No purchase detected on this page — try a product, subscription or checkout page.</p>
          {noPurchasePage && import.meta.env.DEV && (
            <p class="sp-footnote">
              <button class="btn btn--ghost" onClick={() => setDemo(true)}>Try the demo purchase</button>
            </p>
          )}
        </div>
      )}

      {/* Results */}
      {!noPurchasePage && !noPurchase && (
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
          ) : status === "streaming" && cards.length === 0 ? (
            <div class="sp-hero">
              <span class="sp-hero__name" style="opacity:.45">
                {phase === "terms" ? "Reading the terms…" : "Checking the small print…"}
              </span>
            </div>
          ) : null}

          {/* Body */}
          <div class="sp-body">
            {costCard && (
              <CardErrorBoundary name="cost">
                <CostCard
                  costStreams={costStreams}
                  state={costCard.state}
                  horizon={settings.horizon}
                  lockIn={lockIn ?? undefined}
                  priceDrift={driftPayload ?? undefined}
                />
              </CardErrorBoundary>
            )}

            {(lockIn || smallPrint.length > 0) && (
              <CardErrorBoundary name="terms">
                <TermsAccordion lockIn={lockIn} smallPrint={smallPrint} />
              </CardErrorBoundary>
            )}

            {companyCard && (
              <CardErrorBoundary name="company">
                <CompanyCard
                  company={companyCard.payload as AnalyseResult["company"]}
                  state={companyCard.state}
                  flaggedKinds={settings.recordKinds}
                  onFlag={onFlagCompany}
                />
              </CardErrorBoundary>
            )}
          </div>

          {/* Progress */}
          {status === "streaming" && request && (
            <>
              <div class="sp-progress" data-testid="progress">
                <span class="spinner" aria-hidden="true" />
                <span>
                  {phase === "terms"
                    ? "Reading the terms…"
                    : cards.length === 0 ? "Checking the small print…" : `Checking… ${cards.length} of ${TOTAL_CARDS}`}
                </span>
              </div>
              <div aria-hidden="true">
                {Array.from({ length: Math.max(0, TOTAL_CARDS - cards.length) }, (_, i) => (
                  <div key={i} class="sp-placeholder" data-testid="placeholder">
                    <span class="sp-placeholder__line sp-placeholder__line--short" />
                    <span class="sp-placeholder__line" />
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Statutory rights */}
          {status !== "streaming" && !noPurchase && cards.length > 0 && (
            <StatutoryRights purchaseTypes={purchaseTypes} />
          )}

          {request && status === "done" && cards.length === 0 && (
            <p class="empty-state">No results came back for this page.</p>
          )}
        </>
      )}

      {active === undefined && !demo && <div class="loading">Looking at this page…</div>}
      {demo && <p class="sp-footnote">Demo: analysing a canned request ({CANNED_REQUEST.item.name ?? CANNED_REQUEST.item.url}).</p>}
    </div>
  );
}
