/**
 * Purchase detection over saved pages, in Node (linkedom), no browser.
 * Each fixtures/pages/<name>.html has a reviewed <name>.expected.json beside it.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { parseHTML } from "linkedom";
import { detectPurchase, type Detection } from "../src/detect";
import { classifyLink } from "../src/detect/links";
import { isCheckout } from "../src/detect/checkout";
import { RECURRING_PRICE, wordingSignals } from "../src/detect/wording";
import { parsePrice } from "../src/detect/text";
import { PAGE_URLS } from "./pages";

const PAGES = resolve(__dirname, "../../fixtures/pages");
const load = (name: string) => parseHTML(readFileSync(`${PAGES}/${name}.html`, "utf8")).document as unknown as Document;
const html = (body: string, head = "") =>
  parseHTML(`<!doctype html><html><head>${head}</head><body>${body}</body></html>`).document as unknown as Document;
const expected = (name: string) => JSON.parse(readFileSync(`${PAGES}/${name}.expected.json`, "utf8")) as { url: string; detection: Detection };
const run = (name: string) => detectPurchase(PAGE_URLS[name], load(name));

describe("saved pages produce the expected requests", () => {
  for (const name of Object.keys(PAGE_URLS)) {
    it(name, () => {
      const e = expected(name);
      expect(e.url).toBe(PAGE_URLS[name]);
      expect(run(name)).toEqual(e.detection);
    });
  }
});

describe("what each detector finds", () => {
  it("Amazon product: adapter wins, ASIN url, brand from byline, seller from buybox", () => {
    const d = run("amazon-product");
    expect(d).toMatchObject({ status: "purchase", detector: "amazon", checkout: false });
    if (d.status !== "purchase") return;
    expect(d.request.item).toEqual({
      name: "SodaStream Terra Sparkling Water Maker, Black", brand: "SodaStream", price: 89.99,
      seller: "Amazon", manufacturer: "SodaStream UK Ltd", url: "https://www.amazon.co.uk/dp/B09ABC1234", id: "B09ABC1234",
    });
    // The Prime "subscription auto-renews" banner in the header must not make this a subscription.
    expect(d.request.purchase_type_signals).toEqual(["product"]);
    expect(d.request.links.map((l) => l.kind)).toEqual(["terms", "returns", "warranty", "privacy"]);
  });

  it("JSON-LD retailer: Product + Offer from @graph, broken block skipped, care-plan add-on ignored", () => {
    const d = run("jsonld-retailer");
    expect(d).toMatchObject({ status: "purchase", detector: "jsonld" });
    if (d.status !== "purchase") return;
    expect(d.request.item).toMatchObject({ name: "Ninja AF100UK Air Fryer, 3.8 L - Grey", brand: "Ninja", price: 99, seller: "Brightwell Electrical", id: "10215566" });
    expect(d.request.item.url).not.toMatch(/utm_|gclid/);
    expect(d.request.purchase_type_signals).toEqual(["product"]);
    expect(d.request.page_text_snippets.join("\n")).not.toMatch(/newsletter/i);
  });

  it("UK subscription: wording detector, recurring price, membership terms + cancel links", () => {
    const d = run("uk-subscription");
    expect(d).toMatchObject({ status: "purchase", detector: "wording", checkout: false });
    if (d.status !== "purchase") return;
    expect(d.request.item).toMatchObject({ name: "Join Northgate Gym", brand: "Northgate Gyms", price: 24.99 });
    expect(d.request.purchase_type_signals).toEqual(["subscription"]);
    expect(d.request.links.map((l) => l.kind)).toEqual(["terms", "subscription", "cancel", "privacy"]);
  });

  it("brand from the title suffix keeps only the words that spell the domain", () => {
    const page = (title: string, url: string, head = "") => {
      const d = detectPurchase(url, html("<main><p>Membership from £30.99 a month. Cancel any time.</p></main>", `<title>${title}</title>${head}`));
      return d.status === "purchase" ? d.request.item : null;
    };
    // Live puregym.com/join/ (no og:site_name): the suffix was taken whole as the brand.
    expect(page("Choose Your Gym | Join PureGym", "https://www.puregym.com/join/")).toMatchObject({ brand: "PureGym", seller: "PureGym", name: "Choose Your Gym" });
    // A suffix that is all brand stays whole.
    expect(page("Join today | The Gym Group", "https://www.thegymgroup.com/join/")?.brand).toBe("The Gym Group");
    // No words spell the domain: keep the suffix as before.
    expect(page("Plans | Fitness First", "https://www.example-gyms.co.uk/join")?.brand).toBe("Fitness First");
    // An explicit og:site_name is never trimmed.
    expect(page("Choose Your Gym | Join PureGym", "https://www.puregym.com/join/", '<meta property="og:site_name" content="Join PureGym">')?.brand).toBe("Join PureGym");
  });

  it("checkout: badge on, contract + subscription, contract summary found, no personal data", () => {
    const d = run("checkout");
    expect(d).toMatchObject({ status: "purchase", detector: "wording", checkout: true });
    if (d.status !== "purchase") return;
    expect(d.request.item).toMatchObject({ name: "Full Fibre 500", price: 29.99, url: "https://www.fernline.co.uk/checkout/review" });
    expect(d.request.purchase_type_signals).toEqual(["subscription", "contract"]);
    expect(d.request.links.find((l) => l.kind === "contract_summary")?.url).toMatch(/contract-summary-full-fibre-500\.pdf$/);
    // contracts/README.md rule 5: no checkout page text at all.
    expect(d.request.page_text_snippets).toEqual([]);
    const sent = JSON.stringify(d.request);
    for (const personal of ["Sweta", "Acharya", "High Street", "EH1", "sweta@example.com", "07700", "4242", "s3cr3t"]) {
      expect(sent).not.toContain(personal);
    }
  });

  it("no purchase: article about subscriptions, Amazon search, Amazon checkout", () => {
    expect(run("no-purchase-article")).toEqual({ status: "none", checkout: false });
    expect(run("amazon-search")).toEqual({ status: "none", checkout: false });
    // Checkout without product details still lights the badge.
    expect(run("amazon-checkout")).toEqual({ status: "none", checkout: true });
  });

  // 40-URL run 2026-11-08: audible.co.uk keeps its offer in a hero banner outside a near-empty <main>.
  it("wording: a near-empty <main> (app shell) falls back to the whole body", () => {
    const d = detectPurchase("https://www.audible.co.uk/ep/whats-audible", html(
      `<section class="hero"><p>This Season's Biggest Deal | £0.99/mo for 3 months</p><p>£5.99/mo after 3 months - terms apply. Cancel monthly</p></section>
       <main><p>Try it now</p></main>`,
      "<title>Audible</title>",
    ));
    expect(d).toMatchObject({ status: "purchase", detector: "wording" });
    if (d.status === "purchase") expect(d.request.item.price).toBe(0.99);
  });

  it("wording: a full <main> is still the only root, so a news page's support banner outside it is not a purchase", () => {
    const article = Array.from({ length: 20 }, (_, i) => `<p>Paragraph ${i} of a news story about the economy.</p>`).join("");
    const d = detectPurchase("https://www.example-news.co.uk/uk-news", html(
      `<main>${article}</main><section class="support-banner"><p>Support us from £4/month. Cancel anytime.</p></section>`,
    ));
    expect(d.status).toBe("none");
  });
});

describe("detector order and purity", () => {
  it("Amazon adapter beats JSON-LD on Amazon; JSON-LD beats wording elsewhere", () => {
    const ld = `<script type="application/ld+json">{"@type":"Product","name":"LD name","offers":{"price":"1.00"}}</script>`;
    const amazon = html(`<span id="productTitle">Adapter name</span><p>£5 a month subscription, cancel anytime</p>`, ld);
    expect(detectPurchase("https://www.amazon.co.uk/dp/B000000001", amazon)).toMatchObject({ detector: "amazon" });
    const shop = html(`<main><p>£5 a month subscription, cancel anytime</p></main>`, ld);
    const d = detectPurchase("https://shop.example/p/1", shop);
    expect(d).toMatchObject({ detector: "jsonld", request: { item: { name: "LD name" }, purchase_type_signals: ["product", "subscription"] } });
  });

  it("does not modify the document", () => {
    const doc = load("checkout");
    const before = doc.documentElement.outerHTML;
    detectPurchase(PAGE_URLS.checkout, doc);
    expect(doc.documentElement.outerHTML).toBe(before);
  });

  it("ignores non-web URLs and bad input", () => {
    expect(detectPurchase("chrome://extensions", html(""))).toEqual({ status: "none", checkout: false });
    expect(detectPurchase("not a url", html(""))).toEqual({ status: "none", checkout: false });
  });
});

describe("manufacturer (for the exact UK company)", () => {
  it("reads Amazon's details table", () => {
    const doc = html(`<span id="productTitle">PlayStation 5 Pro</span>
      <table id="productDetails_techSpec_section_1"><tr><th>Brand</th><td>PlayStation</td></tr>
      <tr><th> Manufacturer </th><td>\u200eSony Interactive Entertainment Europe Ltd</td></tr></table>`);
    const d = detectPurchase("https://www.amazon.co.uk/dp/B0DGY63Z2H", doc);
    expect(d).toMatchObject({ request: { item: { manufacturer: "Sony Interactive Entertainment Europe Ltd" } } });
  });

  it("reads Amazon's detail bullets, direction marks and all", () => {
    const d = run("amazon-product");
    expect(d).toMatchObject({ request: { item: { manufacturer: "SodaStream UK Ltd" } } });
  });

  it("reads JSON-LD manufacturer, and leaves it out when the page doesn't say", () => {
    const ld = (extra: string) => `<script type="application/ld+json">{"@type":"Product","name":"Body Wash","brand":"Dove",${extra}"offers":{"price":"3.00"}}</script>`;
    const withIt = detectPurchase("https://shop.example/p/1", html("", ld(`"manufacturer":{"@type":"Organization","name":"Unilever UK Ltd"},`)));
    expect(withIt).toMatchObject({ request: { item: { manufacturer: "Unilever UK Ltd" } } });
    const without = detectPurchase("https://shop.example/p/1", html("", ld("")));
    expect(without.status === "purchase" && "manufacturer" in without.request.item).toBe(false);
  });
});

describe("building blocks", () => {
  it("parsePrice", () => {
    expect(parsePrice("£1,299.99")).toBe(1299.99);
    expect(parsePrice("99.00")).toBe(99);
    expect(parsePrice(24.5)).toBe(24.5);
    expect(parsePrice("free")).toBeNull();
  });

  it("recurring price wording", () => {
    for (const s of ["£24.99 a month", "£29.99/month", "£5.99 per month", "£12 pcm", "£9.99 /mo"]) expect(s).toMatch(RECURRING_PRICE);
    for (const s of ["£24.99", "a month ago", "£24.99 a year"]) expect(s).not.toMatch(RECURRING_PRICE);
  });

  it("one 'subscribe' alone isn't a subscription; newsletter lines don't count", () => {
    expect(wordingSignals(["Subscribe to our newsletter", "Free trial for newsletter readers"]).signals).toEqual([]);
    expect(wordingSignals(["Start your free trial", "Cancel anytime"]).signals).toEqual(["subscription"]);
    expect(wordingSignals(["18-month contract"]).signals).toEqual(["contract"]);
  });

  it("classifies terms-type links", () => {
    expect(classifyLink("Contract summary", "/x")).toBe("contract_summary");
    expect(classifyLink("Subscription terms", "/x")).toBe("subscription");
    expect(classifyLink("Terms & Conditions", "/x")).toBe("terms");
    expect(classifyLink("T&Cs apply", "/x")).toBe("terms");
    expect(classifyLink("Read more", "/legal/terms-of-sale")).toBe("terms");
    expect(classifyLink("Returns & refunds", "/x")).toBe("returns");
    expect(classifyLink("Shop TVs", "/tvs")).toBeNull();
  });

  it("checkout detection", () => {
    expect(isCheckout(new URL("https://x.co.uk/checkout/delivery"), html(""))).toBe(true);
    expect(isCheckout(new URL("https://x.co.uk/basket"), html(""))).toBe(true);
    expect(isCheckout(new URL("https://x.co.uk/p/1"), html(`<button>Pay now</button>`))).toBe(true);
    expect(isCheckout(new URL("https://x.co.uk/p/1"), html(`<button>Buy now</button><button>Add to basket</button>`))).toBe(false);
    expect(isCheckout(new URL("https://x.co.uk/cartoons"), html(""))).toBe(false);
  });
});
