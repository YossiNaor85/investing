/* Investing UI: the "Your assets" picker, and for each asset a first page of
   boxes that open its sections. Addresses:
     #IREN            first page (overview)
     #IREN/graphs/1Y  graphs, with the 1Y / 3M / 1D window
     #IREN/ratios     fundamental ratios
     #IREN/ratings    analyst rating changes of the past year, with reasons (from the Analysts box)
     #IREN/news, #IREN/info, #IREN/analyst, #IREN/sentiment   empty for now
   Data comes from data/<TICKER>.js, written by each asset's pipeline in UI/asset/<ticker>_page/.
   When the page is served by UI/server.py, the Refresh button runs that pipeline. */
(() => {
  "use strict";

  const SCHEMA = 1;                 // the data format this script reads (UI/pipeline/asset_page.py SCHEMA)
  const REREAD_MS = 5 * 60 * 1000;  // re-read the data files this often
  const POLL_MS = 1000;             // status polling while a refresh runs
  const WINDOWS = { "1Y": "1 year", "3M": "3 months", "1D": "1 day" };
  const VIEWS = {
    overview: "Overview",
    graphs: "Graphs",
    ratios: "Fundamental ratios",
    ratings: "Analyst rating changes",
    news: "News",
    info: "Info",
    analyst: "Connect the dots",
    sentiment: "Sentiment compass",
  };
  const EMPTY_VIEWS = ["news", "info", "analyst", "sentiment"];
  const PARENT_VIEW = { ratings: "ratios" };  // a page opened from another page, for the breadcrumb
  const BOXES = [
    { view: "graphs", title: "Graphs", text: "Trading points over 1 year, 3 months and 1 day, with volume and the econometric measures." },
    { view: "ratios", title: "Fundamental ratios", text: "Valuation, profitability, growth, balance sheet, ownership and analysts." },
    { view: "news", title: "News", text: "Company, domain and macro news.", soon: true },
    { view: "info", title: "Info", text: "The business, its domain, peers and plans.", soon: true },
    { view: "analyst", title: "Connect the dots", text: "The analyst's story: why it moves and what to watch.", soon: true },
    { view: "sentiment", title: "Sentiment compass", text: "The market's mood around this asset.", soon: true },
  ];
  const HIGH_VOLUME = 1.5;          // same threshold as the updater
  const TICKER_RE = /^[A-Z0-9.\-]{1,12}$/;
  const THEME_KEY = "investing-theme";
  const MINUS = "−";
  const DASH = "—";
  const SVG_NS = "http://www.w3.org/2000/svg";

  const state = {
    ticker: null,
    view: "overview",
    shownView: null,  // the view on screen, to scroll to the top only when it changes
    window: "1Y",
    data: null,
    currency: "USD",
    tableOpen: false,
    hoverIndex: null,
    server: false,
    refreshing: false,
    addOpen: false,   // the Add asset form is showing in the menu
    adding: null,     // ticker being added, while the skill runs
    deleting: null,   // ticker being deleted
  };

  const $ = (id) => document.getElementById(id);

  // -------------------------------------------------------------- formatting

  const isNum = (v) => typeof v === "number" && Number.isFinite(v);
  const minus = (v) => (v < 0 ? MINUS : "");
  const fixed = (v, d) =>
    Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

  function compact(v) {
    const a = Math.abs(v);
    for (const [size, unit] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]]) {
      if (a >= size) {
        const n = a / size;
        return fixed(n, n < 10 ? 2 : n < 100 ? 1 : 0) + unit;
      }
    }
    return fixed(a, a < 10 && a !== Math.round(a) ? 2 : 0);
  }

  function formatDate(iso, extra) {
    const [y, m, d] = iso.split("-").map(Number);
    const opts = Object.assign({ timeZone: "UTC", month: "short", day: "numeric", year: "numeric" }, extra || {});
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", opts);
  }

  // Money uses the asset's trading currency; codes without a symbol print as "ILA 1,234.00".
  const CURRENCY_SYMBOLS = { USD: "$", EUR: "€", GBP: "£", JPY: "¥", ILS: "₪", CAD: "C$", AUD: "A$", HKD: "HK$" };
  const prefixFor = (cur) => CURRENCY_SYMBOLS[cur || "USD"] || cur + " ";
  const money = (v, cur) => minus(v) + prefixFor(cur || state.currency) + fixed(v, 2);
  const moneyCompact = (v, cur) => minus(v) + prefixFor(cur || state.currency) + compact(v);

  const FORMATS = {
    money: (v) => money(v),
    money_compact: (v) => moneyCompact(v),
    money_range: (v) => (Array.isArray(v) ? money(v[0]) + " – " + money(v[1]) : DASH),
    usd: (v) => money(v, "USD"),
    usd_compact: (v) => moneyCompact(v, "USD"),
    pct: (v) => minus(v) + fixed(v * 100, 1) + "%",
    pct_signed: (v) => (v > 0 ? "+" : minus(v)) + fixed(v * 100, 1) + "%",
    x: (v) => minus(v) + fixed(v, 2) + "×",
    num: (v) => minus(v) + fixed(v, 2),
    int: (v) => minus(v) + fixed(v, 0),
    int_compact: (v) => minus(v) + compact(v),
    days: (v) => fixed(v, 1) + " days",
    date: (v) => formatDate(v),
    text: (v) => String(v),
  };

  function format(value, kind) {
    if (value === null || value === undefined || value === "") return DASH;
    if (typeof value === "number" && !Number.isFinite(value)) return DASH;
    return (FORMATS[kind] || FORMATS.num)(value);
  }

  // ------------------------------------------------------------------- DOM

  /** Build an element. Strings become text nodes, so data never becomes markup. */
  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }

  function svgEl(tag, attrs, text) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function deltaNode(pct, prefix) {
    const dir = pct > 0 ? "up" : pct < 0 ? "down" : "flat";
    const arrow = pct > 0 ? "▲ " : pct < 0 ? "▼ " : "";
    const words = dir === "up" ? "up " : dir === "down" ? "down " : "";
    return h("span", { class: "delta " + dir, "aria-label": words + format(Math.abs(pct), "pct") },
      h("span", { class: "delta-arrow", "aria-hidden": "true", text: arrow }),
      (prefix ? prefix + " " : "") + format(pct, "pct_signed"));
  }

  // --------------------------------------------------------------- loading

  /** Load a data file with a <script> tag; this also works from file://. */
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = src + "?v=" + Date.now();
      el.onload = () => { el.remove(); resolve(); };
      el.onerror = () => { el.remove(); reject(new Error("missing " + src)); };
      document.head.append(el);
    });
  }

  function assets() {
    const list = window.INVESTING_ASSETS;
    return Array.isArray(list) && list.length ? list : [{ ticker: "IREN", name: "IREN", has_data: false }];
  }

  async function loadAssets() {
    try { await loadScript("data/assets.js"); } catch (e) { /* no data written yet */ }
    renderMenu();
  }

  async function loadAsset(ticker) {
    window.INVESTING_DATA = window.INVESTING_DATA || {};
    try {
      await loadScript("data/" + ticker + ".js");
    } catch (e) {
      return null;
    }
    return window.INVESTING_DATA[ticker] || null;
  }

  // ------------------------------------------------------------ assets menu

  function renderMenu() {
    const menu = $("assets-menu");
    menu.textContent = "";
    menu.append(h("div", { class: "menu-head", text: "Assets we follow" }));
    for (const a of assets()) {
      const item = h("button", { class: "menu-item", type: "button", role: "menuitem", "data-ticker": a.ticker },
        h("span", { class: "menu-ticker", text: a.ticker }),
        h("span", { class: "menu-name", text: a.name && a.name !== a.ticker ? a.name : "" }),
        h("span", { class: "menu-price", text: isNum(a.price) ? money(a.price, a.currency || "USD") : "" }),
        isNum(a.change_pct) ? deltaNode(a.change_pct) : h("span", { class: "muted small", text: a.has_data ? "" : "no data yet" }));
      item.addEventListener("click", () => { closeMenu(); go(a.ticker, "overview"); });
      const followed = (window.INVESTING_ASSETS || []).some((x) => x.ticker === a.ticker);
      const del = h("button", { class: "menu-delete", type: "button", role: "menuitem", "data-delete": a.ticker,
        "aria-label": "Delete " + a.ticker,
        title: state.server ? "Delete " + a.ticker + " from Your assets" : "Deleting needs the UI server",
        disabled: !state.server || !followed || state.deleting ? true : null,
        text: state.deleting === a.ticker ? "…" : "✕" });
      del.addEventListener("click", (e) => { e.stopPropagation(); deleteAsset(a.ticker); });
      menu.append(h("div", { class: "menu-row", role: "none" }, item, del));
    }
    const add = h("button", { class: "menu-item menu-add", type: "button", role: "menuitem",
      "aria-expanded": String(state.addOpen), disabled: state.adding ? true : null },
      h("span", { class: "menu-ticker", "aria-hidden": "true", text: "+" }),
      h("span", { class: "menu-name", text: state.adding ? "Adding " + state.adding + "…" : "Add asset" }));
    add.addEventListener("click", () => {
      state.addOpen = !state.addOpen;
      renderMenu();
      if (state.addOpen) $("add-ticker").focus();
    });
    menu.append(add);
    if (state.addOpen) menu.append(addForm());
  }

  function addForm() {
    const input = h("input", { id: "add-ticker", class: "add-input", type: "text", autocomplete: "off",
      spellcheck: "false", maxlength: "12", placeholder: "Ticker, e.g. NVDA", "aria-label": "Ticker to add" });
    const submit = h("button", { class: "btn btn-primary btn-small", type: "submit", text: "Add" });
    if (!state.server) { input.disabled = true; submit.disabled = true; }
    const form = h("form", { class: "add-form" },
      h("div", { class: "add-row" }, input, submit),
      h("p", { class: "add-help", text: state.server
        ? "Builds the page and its pipeline on this computer with a Python script, then opens it. Takes about half a minute."
        : "Adding needs the UI server: start it with UI\\link\\start-investing-ui.cmd." }));
    form.addEventListener("submit", (e) => { e.preventDefault(); addAsset(input.value); });
    return form;
  }

  function menuItems() {
    return Array.from($("assets-menu").querySelectorAll(".menu-item, .menu-delete")).filter((el) => !el.disabled);
  }

  function openMenu() {
    $("assets-menu").hidden = false;
    $("assets-button").setAttribute("aria-expanded", "true");
    const items = menuItems();
    const current = items.find((el) => el.dataset.ticker === state.ticker);
    (current || items[0])?.focus();
  }

  function closeMenu(returnFocus) {
    if ($("assets-menu").hidden) return;
    $("assets-menu").hidden = true;
    $("assets-button").setAttribute("aria-expanded", "false");
    if (returnFocus) $("assets-button").focus();
  }

  function wireMenu() {
    $("assets-button").addEventListener("click", () => ($("assets-menu").hidden ? openMenu() : closeMenu()));
    $("assets-menu").addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" && e.key !== "Escape") return;  // typing a ticker
      const items = menuItems();
      const i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { items[(i + 1) % items.length].focus(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { items[(i - 1 + items.length) % items.length].focus(); e.preventDefault(); }
      else if (e.key === "Escape") { closeMenu(true); e.preventDefault(); }
    });
    document.addEventListener("pointerdown", (e) => {
      if (!e.target.closest(".menu-wrap")) closeMenu();
    });
  }

  // ---------------------------------------------------------------- routing

  function parseHash() {
    const parts = decodeURIComponent(location.hash.replace(/^#/, "")).split("/").filter(Boolean);
    const ticker = (parts[0] || "").toUpperCase();
    let view = "overview", win = null;
    if (WINDOWS[parts[1]]) {  // older links, like #IREN/1Y, open the graphs
      view = "graphs";
      win = parts[1];
    } else if (VIEWS[parts[1]]) {
      view = parts[1];
      if (view === "graphs" && WINDOWS[parts[2]]) win = parts[2];
    }
    return { ticker: TICKER_RE.test(ticker) ? ticker : null, view, window: win };
  }

  function hashFor(ticker, view, win) {
    if (!view || view === "overview") return "#" + ticker;
    return "#" + ticker + "/" + view + (view === "graphs" ? "/" + (win || state.window) : "");
  }

  /** Go to an asset's view. Changing the hash adds a history entry, so Back works. */
  function go(ticker, view, win) {
    const next = hashFor(ticker, view || "overview", win);
    if (location.hash === next) route();
    else location.hash = next;
  }

  /** Show what the address names: load the asset's data when needed, then its view. */
  async function route() {
    const r = parseHash();
    if (!r.ticker) return;
    if (r.window) state.window = r.window;
    state.view = r.view;
    if (r.ticker !== state.ticker || !state.data) {
      state.ticker = r.ticker;
      const data = await loadAsset(r.ticker);
      if (!data) { showMissing(r.ticker); return; }
      render(data);
      if (state.server) watchReasons(r.ticker, true);  // a search still running from before a reload
    } else {
      showView();
    }
  }

  function showMissing(ticker) {
    $("empty-state").hidden = true;
    $("asset-view").hidden = true;
    $("missing-state").hidden = false;
    $("missing-title").textContent = "No data for " + ticker + " yet";
  }

  // ---------------------------------------------------------------- render

  function render(data) {
    state.data = data;
    state.currency = data.currency || "USD";
    state.hoverIndex = null;
    $("empty-state").hidden = true;
    $("missing-state").hidden = true;
    $("asset-view").hidden = false;
    renderHead(data);
    renderKpis(data.kpis);
    renderBoxes(data);
    const hasRatings = !!(data.analyst_actions && (data.analyst_actions.rows || []).length);
    renderGroups($("ratios"), data.ratios, (g) => g.id === "analysts" && hasRatings
      ? h("a", { class: "btn btn-small group-link", href: hashFor(data.ticker, "ratings") }, "Rating changes, past year \u2192")
      : null);
    renderAnalystTable(data.analyst_actions);
    renderGroups($("econ"), data.econometrics);
    renderFooter(data);
    showView();
  }

  /** Every analyst update of the past year, newest first. Each change of rating or price
   *  target gets the firm's reason when it's known; a plain reiteration needs none. */
  function renderAnalystTable(aa) {
    const rows = (aa && aa.rows) || [];
    $("analyst-card").hidden = !rows.length;
    $("analyst-none").hidden = !!rows.length;
    const host = $("analyst-table");
    host.textContent = "";
    if (!rows.length) return;
    const changed = rows.filter(isChange).length;
    let sub = rows.length + " analyst updates since " + formatDate(aa.since) + ", newest first; " + changed +
      " of them changed the rating or the price target." +
      " Why: the firm's reason for the change, as reported in the news." +
      " \u201cInferred\u201d marks a reason read from the timing, such as results released that week.";
    if (aa.pending) sub += " " + (aa.pending === 1 ? "1 change" : aa.pending + " changes") + " not looked into yet.";
    $("analyst-sub").textContent = sub;
    const tbody = h("tbody");
    for (const r of rows) {
      const dir = r.action === "upgrade" ? "up" : r.action === "downgrade" ? "down" : "";
      tbody.append(h("tr", {},
        h("td", { class: "nowrap", text: formatDate(r.date) }),
        h("th", { scope: "row", text: r.firm }),
        h("td", {},
          h("span", { class: "rating", text: r.rating || DASH }),
          r.action ? h("span", { class: "rating-action" },
            dir ? h("span", { class: "delta " + dir, "aria-hidden": "true", text: dir === "up" ? "▲ " : "▼ " }) : null,
            r.action) : null),
        h("td", { text: r.previous || DASH }),
        targetCell(r),
        whyCell(r)));
    }
    host.append(h("table", { class: "data-table analyst-table" },
      h("caption", { class: "sr-only", text: "Analyst rating changes over the past year, newest first" }),
      h("thead", {}, h("tr", {}, ...["Date", "Firm", "Rating", "Previous rating", "Price target", "Why"].map((x) =>
        h("th", { scope: "col", class: x === "Price target" ? "num" : null, text: x })))),
      tbody));
  }

  /** A new rating (upgrade, downgrade, new coverage) or a new price target: these get a reason. */
  function isChange(r) {
    if (r.rating_changed !== undefined || r.target_changed !== undefined) return !!(r.rating_changed || r.target_changed);
    const target = isNum(r.target) && isNum(r.prior_target) && r.target !== r.prior_target;
    return (r.rating || "") !== (r.previous || "") || target;
  }

  /** The price target, prior → new, with ▲ for a raise and ▼ for a cut. */
  function targetCell(r) {
    const cell = h("td", { class: "num nowrap" });
    if (isNum(r.target) && isNum(r.prior_target) && r.target !== r.prior_target) {
      const up = r.target > r.prior_target;
      cell.append(h("span", { class: "delta " + (up ? "up" : "down"), "aria-hidden": "true", text: up ? "\u25b2 " : "\u25bc " }),
        h("span", { class: "sr-only", text: up ? "raised from " : "cut from " }));
    }
    cell.append(targetText(r));
    return cell;
  }

  /** The reason, then a line saying where it comes from: the article, or "Inferred". Empty when nothing changed. */
  function whyCell(r) {
    const cell = h("td", { class: "why" });
    if (!isChange(r)) return cell;
    if (r.searched === false) {
      cell.append(h("span", { class: "muted", text: state.searching === state.ticker ? "Looking into it\u2026" : "Not looked into yet" }));
      return cell;
    }
    if (!r.why) {
      cell.append(h("span", { class: "muted", text: "No reason found" }));
      return cell;
    }
    const url = /^https?:\/\//.test(r.why_url || "") ? r.why_url : null;
    const inferred = r.why_basis === "inferred";
    const source = r.why_source || (url ? "Article" : null);
    cell.append(h("span", { text: r.why }));
    if (inferred || source) {
      cell.append(h("span", { class: "why-source" },
        inferred ? h("span", { class: "inferred", text: "Inferred" }) : null,
        inferred && source ? " · " : null,
        source && url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", title: "Open the article", text: source })
          : source));
    }
    return cell;
  }

  function targetText(r) {
    if (isNum(r.target) && isNum(r.prior_target) && r.prior_target !== r.target) {
      return format(r.prior_target, "money") + " → " + format(r.target, "money");
    }
    return isNum(r.target) ? format(r.target, "money") : DASH;
  }

  /** Show the current view's section; the chart is drawn only once its section is visible. */
  function showView() {
    const v = state.view;
    for (const name of ["overview", "graphs", "ratios", "ratings"]) $("view-" + name).hidden = v !== name;
    $("view-empty").hidden = !EMPTY_VIEWS.includes(v);
    $("placeholder-title").textContent = VIEWS[v];
    $("crumbs").hidden = v === "overview";
    $("crumb-asset").textContent = state.ticker;
    $("crumb-asset").setAttribute("href", hashFor(state.ticker, "overview"));
    $("crumb-current").textContent = VIEWS[v];
    const parent = PARENT_VIEW[v];
    $("crumb-parent").hidden = $("crumb-parent-sep").hidden = !parent;
    if (parent) {
      $("crumb-parent").textContent = VIEWS[parent];
      $("crumb-parent").setAttribute("href", hashFor(state.ticker, parent));
    }
    $("delete-asset").hidden = v !== "overview";
    document.title = state.ticker + (v === "overview" ? "" : " · " + VIEWS[v]) + " · Investing";
    if (v === "graphs") renderWindow();
    const key = state.ticker + "/" + v;
    if (state.shownView !== key) {
      state.shownView = key;
      window.scrollTo(0, 0);
    }
  }

  function renderBoxes(d) {
    const host = $("boxes");
    host.textContent = "";
    for (const b of BOXES) {
      host.append(h("a", { class: "box" + (b.soon ? " box-soon" : ""), href: hashFor(d.ticker, b.view) },
        h("div", { class: "box-head" },
          h("h3", { class: "box-title", text: b.title }),
          b.soon ? h("span", { class: "badge", text: "Coming soon" }) : null),
        h("p", { class: "box-text", text: b.text }),
        boxPreview(d, b.view)));
    }
  }

  function findItem(groups, label) {
    for (const g of groups || []) for (const it of g.items || []) if (it.label === label) return it;
    return null;
  }

  function boxPreview(d, view) {
    if (view === "graphs") {
      const pts = ((d.series || {})["1Y"] || {}).points || [];
      if (pts.length < 2) return null;
      return h("div", { class: "box-preview" }, sparkline(pts.map((p) => p.c)),
        h("span", { class: "box-stat", text: "1 year " + format(pts[pts.length - 1].c / pts[0].c - 1, "pct_signed") }));
    }
    if (view === "ratios") {
      const picks = d.kind === "EQUITY" || !d.kind
        ? ["Price / sales (TTM)", "Net margin", "Debt / equity"]
        : ["Total assets", "Expense ratio", "Yield"];
      const items = picks.map((label) => findItem(d.ratios, label)).filter(Boolean);
      if (!items.length) return null;
      return h("dl", { class: "box-facts" }, ...items.map((it) =>
        h("div", {}, h("dt", { text: it.label }), h("dd", { text: format(it.value, it.fmt) }))));
    }
    return null;
  }

  function sparkline(values) {
    const vals = values.filter(isNum);
    const w = 240, ht = 44, pad = 4;
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const x = (i) => pad + (i / (vals.length - 1)) * (w - 2 * pad);
    const y = (v) => ht - pad - ((v - lo) / (hi - lo || 1)) * (ht - 2 * pad);
    const svg = svgEl("svg", { class: "spark", viewBox: "0 0 " + w + " " + ht, "aria-hidden": "true" });
    svg.append(svgEl("path", { d: vals.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1)).join(""), class: "spark-line" }));
    svg.append(svgEl("circle", { cx: x(vals.length - 1), cy: y(vals[vals.length - 1]), r: 3.5, class: "spark-dot" }));
    return svg;
  }

  function renderHead(d) {
    $("asset-title").textContent = d.name;
    $("asset-sub").textContent = [d.ticker, d.exchange, d.currency, d.classification].filter(Boolean).join(" · ");
    $("asset-note").textContent = d.note || "";
    $("asset-note").hidden = !d.note;
    updateDeleteButton();
    const q = d.quote || {};
    $("quote-price").textContent = format(q.price, "money");
    const change = $("quote-change");
    change.textContent = "";
    if (isNum(q.change_pct)) {
      const abs = isNum(q.change) ? (q.change > 0 ? "+" : minus(q.change)) + prefixFor(state.currency) + fixed(q.change, 2) : "";
      change.append(deltaNode(q.change_pct, abs), h("span", { class: "muted small", text: " vs previous close" }));
    }
    const parts = [];
    if (q.last_close_date) parts.push("Last close " + formatDate(q.last_close_date));
    if (q.extended && isNum(q.extended.price)) {
      parts.push(q.extended.label + " " + format(q.extended.price, "money") + " (" + format(q.extended.change_pct, "pct_signed") + ")");
    } else if (q.market_state) {
      parts.push({ PRE: "Pre-market", PREPRE: "Pre-market", REGULAR: "Market open", POST: "After hours", POSTPOST: "After hours", CLOSED: "Market closed" }[q.market_state] || q.market_state);
    }
    parts.push("Updated " + updatedAt(d));
    $("quote-meta").textContent = parts.join(" · ");
  }

  function updatedAt(d) {
    return new Date(d.updated_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function renderKpis(kpis) {
    const host = $("kpis");
    host.textContent = "";
    for (const k of kpis || []) {
      host.append(h("div", { class: "tile" },
        h("div", { class: "tile-label", text: k.label }),
        h("div", { class: "tile-value", text: format(k.value, k.fmt) }),
        k.note ? h("div", { class: "tile-note", text: k.note }) : null));
    }
  }

  function renderGroups(host, groups, extra) {
    host.textContent = "";
    for (const g of groups || []) {
      const rows = h("dl", { class: "rows" });
      for (const it of g.items || []) {
        rows.append(h("div", { class: "row" },
          h("dt", {}, it.label, it.hint ? h("span", { class: "row-hint", text: it.hint }) : null),
          h("dd", {},
            h("span", { class: "value", text: format(it.value, it.fmt) }),
            it.note ? h("span", { class: "row-note", text: it.note }) : null)));
      }
      host.append(h("section", { class: "group" },
        h("h3", { text: g.title }),
        g.note ? h("p", { class: "group-note", text: g.note }) : null,
        rows,
        extra ? extra(g) : null));
    }
  }

  function renderFooter(d) {
    const box = $("warnings");
    box.textContent = "";
    const warnings = (d.warnings || []).slice();
    if (isNum(d.schema) && d.schema > SCHEMA) {
      warnings.push("This data uses a newer format (" + d.schema + ") than the page understands (" + SCHEMA + "); update UI/static/app.js.");
    }
    for (const w of warnings) box.append(h("p", { text: w }));
    box.hidden = !warnings.length;
    $("source").textContent = "Source: " + d.source + ". Updated " + updatedAt(d) + " (your time).";
  }

  // ------------------------------------------------------------ the window

  function renderWindow() {
    for (const b of document.querySelectorAll("[data-window]")) {
      b.setAttribute("aria-pressed", String(b.dataset.window === state.window));
    }
    const series = state.data.series && state.data.series[state.window];
    $("chart-title").textContent = "Trading points · " + WINDOWS[state.window];
    $("chart-sub").textContent = series && series.points.length ? windowSummary(series) : "No data for this window.";
    renderLegend(series);
    drawChart(series);
    renderTable(series);
  }

  function extremes(points) {
    let hi = -Infinity, lo = Infinity;
    for (const p of points) {
      if (isNum(p.h) && p.h > hi) hi = p.h;
      if (isNum(p.l) && p.l < lo) lo = p.l;
    }
    return { hi, lo };
  }

  function windowSummary(sr) {
    const p = sr.points;
    const first = p[0], last = p[p.length - 1];
    const { hi, lo } = extremes(p);
    if (sr.interval === "1m") {
      const base = isNum(sr.prev_close) ? sr.prev_close : first.o;
      const end = isNum(sr.session_close) ? sr.session_close : last.c;  // official close when the session is over
      return "Session of " + formatDate(sr.session) + " · " + format(end / base - 1, "pct_signed") +
        " vs previous close · range " + format(lo, "money") + "–" + format(hi, "money") +
        " · " + p.length + " one-minute bars, regular hours, US Eastern time";
    }
    return formatDate(first.t) + " – " + formatDate(last.t) + " · " + format(last.c / first.c - 1, "pct_signed") +
      " · high " + format(hi, "money") + " · low " + format(lo, "money") + " · " + p.length + " trading days";
  }

  function renderLegend(sr) {
    const host = $("chart-legend");
    host.textContent = "";
    if (!sr) return;
    const entry = (shape, cls, label) => h("span", { class: "legend-item" },
      h("span", { class: "key " + shape + " " + cls, "aria-hidden": "true" }), label);
    host.append(entry("line", "key-price", "Close"), entry("line", "key-ref", sr.ref_label));
    if (sr.interval === "1m") {
      if (isNum(sr.prev_close)) host.append(entry("line", "key-prev", "Previous close"));
      host.append(entry("rect", "key-session", "First 90 and last 30 minutes"), entry("rect", "key-volume", "Volume"));
    } else {
      host.append(entry("rect", "key-volume", "Volume"),
        entry("rect", "key-volume-high", "Volume ≥ " + HIGH_VOLUME + "× its 20-day average"));
    }
  }

  // ----------------------------------------------------------------- chart

  function niceTicks(min, max, count) {
    if (!(max > min)) max = min + 1;
    const raw = (max - min) / Math.max(1, count - 1);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
    const out = [];
    for (let v = Math.floor(min / step) * step; v <= Math.ceil(max / step) * step + step / 2; v += step) {
      out.push(Number(v.toFixed(10)));
    }
    return out;
  }

  function weekStart(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const t = Date.UTC(y, m - 1, d);
    const back = (new Date(t).getUTCDay() + 6) % 7;  // days since Monday
    return new Date(t - back * 864e5).toISOString().slice(0, 10);
  }

  function xTickIndexes(sr, win, step) {
    const p = sr.points;
    const candidates = [];
    p.forEach((pt, i) => {
      if (sr.interval === "1m") { if (i === 0 || pt.t.endsWith(":00")) candidates.push(i); }
      else if (win === "1Y") { if (i > 0 && pt.t.slice(0, 7) !== p[i - 1].t.slice(0, 7)) candidates.push(i); }
      else if (i > 0 && weekStart(pt.t) !== weekStart(p[i - 1].t)) candidates.push(i);
    });
    const out = [];
    let lastX = -Infinity;
    for (const i of candidates) {
      const x = (i + 0.5) * step;
      if (x - lastX >= 64) { out.push(i); lastX = x; }
    }
    return out;
  }

  function xLabel(pt, sr, win, first) {
    if (sr.interval === "1m") return pt.t.replace(/^0/, "");
    const [y, m, d] = pt.t.split("-").map(Number);
    const date = new Date(Date.UTC(y, m - 1, d));
    if (win === "1Y") {
      return date.toLocaleDateString("en-US", { timeZone: "UTC", month: "short" }) + (m === 1 || first ? " " + y : "");
    }
    return date.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  }

  function barPath(x, y, w, ht, r) {
    r = Math.min(r, w / 2, ht);
    return "M" + x + "," + (y + ht) + "V" + (y + r) + "Q" + x + "," + y + " " + (x + r) + "," + y +
      "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) + "V" + (y + ht) + "Z";
  }

  function ariaSummary(sr) {
    const p = sr.points;
    const first = p[0], last = p[p.length - 1];
    const { hi, lo } = extremes(p);
    const when = (pt) => (sr.interval === "1m" ? pt.t + " ET" : formatDate(pt.t));
    return state.data.ticker + " close price, " + WINDOWS[state.window] + ": " + format(first.c, "money") + " at " + when(first) +
      " to " + format(last.c, "money") + " at " + when(last) + "; high " + format(hi, "money") + ", low " + format(lo, "money") +
      ". Volume is shown below the price. The table view lists every point.";
  }

  function drawChart(sr) {
    const host = $("chart");
    host.textContent = "";
    host.onkeydown = host.onfocus = host.onblur = null;
    if (!sr || !sr.points || !sr.points.length) return;

    const pts = sr.points;
    const n = pts.length;
    const intraday = sr.interval === "1m";
    const width = Math.max(300, Math.floor(host.clientWidth || 800));
    const narrow = width < 560;
    const M = { top: 24, right: narrow ? 54 : 66, bottom: 26, left: narrow ? 46 : 56 };
    const priceH = narrow ? 210 : 290, gap = 20, volH = narrow ? 52 : 72;
    const plotW = width - M.left - M.right;
    const priceBottom = M.top + priceH;
    const volTop = priceBottom + gap;
    const bottom = volTop + volH;
    const height = bottom + M.bottom;
    const step = plotW / n;
    const xAt = (i) => M.left + (i + 0.5) * step;

    // price scale: the drawn lines, plus the previous close on the 1-day window
    let lo = Infinity, hi = -Infinity;
    for (const p of pts) for (const v of [p.c, p.ref]) if (isNum(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (intraday && isNum(sr.prev_close)) { lo = Math.min(lo, sr.prev_close); hi = Math.max(hi, sr.prev_close); }
    const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.02 || 1;
    const yTicks = niceTicks(lo - pad, hi + pad, narrow ? 4 : 5);
    const yMin = yTicks[0], yMax = yTicks[yTicks.length - 1];
    const yStep = yTicks.length > 1 ? yTicks[1] - yTicks[0] : 1;
    const yAt = (v) => priceBottom - ((v - yMin) / (yMax - yMin)) * priceH;
    const priceTick = (v) => prefixFor(state.currency) + fixed(v, yStep >= 1 ? 0 : 2);

    // volume scale: its own panel and axis, never a second y-axis on the price.
    // Intraday, the opening auction can dwarf every other minute, so the scale is
    // capped and the capped bars carry their real value as a label.
    const vMax = Math.max(1, ...pts.map((p) => p.v || 0));
    let vScale = vMax;
    if (intraday && n > 20) {
      const sorted = pts.map((p) => p.v || 0).sort((a, b) => a - b);
      const p98 = sorted[Math.floor(sorted.length * 0.98)];
      if (p98 > 0 && vMax > p98 * 3) vScale = p98 * 1.15;
    }
    const vTicks = niceTicks(0, vScale, 3);
    const vTop = vTicks[vTicks.length - 1];
    const vAt = (v) => bottom - (v / vTop) * volH;

    const svg = svgEl("svg", {
      width, height, viewBox: "0 0 " + width + " " + height, class: "chart-svg",
      role: "img", "aria-label": ariaSummary(sr),
    });

    // the doc's windows: institutions act in the first 90 minutes; the last 30 are noisy
    if (intraday) {
      const indexAt = (hhmm) => { const i = pts.findIndex((p) => p.t >= hhmm); return i === -1 ? n : i; };
      for (const [a, b, label] of [[0, indexAt("11:00"), "First 90 min"], [indexAt("15:30"), n, "Last 30 min"]]) {
        if (b <= a) continue;
        const x0 = M.left + a * step, x1 = M.left + b * step;
        svg.append(svgEl("rect", { x: x0, y: M.top, width: x1 - x0, height: bottom - M.top, class: "session-band" }));
        svg.append(svgEl("text", { x: x0 + 4, y: M.top - 8, class: "band-label" }, label));
      }
    }

    for (const t of yTicks) {
      const y = yAt(t);
      svg.append(svgEl("line", { x1: M.left, x2: M.left + plotW, y1: y, y2: y, class: "grid" }));
      svg.append(svgEl("text", { x: M.left - 8, y: y + 4, class: "tick", "text-anchor": "end" }, priceTick(t)));
    }
    svg.append(svgEl("text", { x: M.left, y: volTop - 6, class: "panel-label" }, "Volume"));
    svg.append(svgEl("line", { x1: M.left, x2: M.left + plotW, y1: vAt(vTop), y2: vAt(vTop), class: "grid" }));
    svg.append(svgEl("text", { x: M.left - 8, y: vAt(vTop) + 4, class: "tick", "text-anchor": "end" }, compact(vTop)));
    svg.append(svgEl("line", { x1: M.left, x2: M.left + plotW, y1: bottom, y2: bottom, class: "axis" }));

    const ticks = xTickIndexes(sr, state.window, step);
    ticks.forEach((i, k) => {
      const x = xAt(i);
      svg.append(svgEl("line", { x1: x, x2: x, y1: bottom, y2: bottom + 4, class: "axis" }));
      svg.append(svgEl("text", { x, y: bottom + 17, class: "tick", "text-anchor": "middle" }, xLabel(pts[i], sr, state.window, k === 0)));
    });

    if (intraday && isNum(sr.prev_close)) {
      const y = yAt(sr.prev_close);
      svg.append(svgEl("line", { x1: M.left, x2: M.left + plotW, y1: y, y2: y, class: "prev-line" }));
      // Label the line at the end where the price is farther from it (left unless the right is
      // clearly clearer), on the side away from the price, so it doesn't sit on the price labels.
      const closes = pts.map((p) => p.c).filter(isNum);
      const left = { x: M.left + 6, anchor: "start", c: closes[0] };
      const right = { x: M.left + plotW - 6, anchor: "end", c: closes[closes.length - 1] };
      const side = Math.abs(yAt(right.c) - y) > Math.abs(yAt(left.c) - y) + 8 ? right : left;
      const below = yAt(side.c) < y && y + 14 < priceBottom - 2;
      svg.append(svgEl("text", { x: side.x, y: below ? y + 14 : y - 6, class: "ref-label", "text-anchor": side.anchor },
        "Previous close " + format(sr.prev_close, "money")));
    }

    const path = (key) => {
      let d = "", pen = "M";
      pts.forEach((p, i) => {
        if (!isNum(p[key])) { pen = "M"; return; }
        d += pen + xAt(i).toFixed(1) + "," + yAt(p[key]).toFixed(1);
        pen = "L";
      });
      return d;
    };
    const firstI = pts.findIndex((p) => isNum(p.c));
    let lastI = n - 1;
    while (lastI > 0 && !isNum(pts[lastI].c)) lastI--;
    const closeD = path("c");
    svg.append(svgEl("path", {
      d: closeD + "L" + xAt(lastI).toFixed(1) + "," + priceBottom + "L" + xAt(firstI).toFixed(1) + "," + priceBottom + "Z",
      class: "area",
    }));
    svg.append(svgEl("path", { d: path("ref"), class: "line-ref" }));
    svg.append(svgEl("path", { d: closeD, class: "line-price" }));

    const bw = Math.max(1, Math.min(24, step * 0.7));
    const vol = svgEl("g", { class: "volume" });
    let biggestCapped = -1;
    pts.forEach((p, i) => {
      if (!p.v) return;
      if (p.v > vTop && (biggestCapped < 0 || p.v > pts[biggestCapped].v)) biggestCapped = i;
      const y = vAt(Math.min(p.v, vTop)), ht = Math.max(0.5, bottom - y), x = xAt(i) - bw / 2;
      const cls = !intraday && isNum(p.vr) && p.vr >= HIGH_VOLUME ? "vol vol-high" : "vol";
      vol.append(bw >= 8
        ? svgEl("path", { d: barPath(x, y, bw, ht, 4), class: cls })
        : svgEl("rect", { x: x.toFixed(2), y: y.toFixed(1), width: bw.toFixed(2), height: ht.toFixed(1), class: cls }));
    });
    svg.append(vol);
    if (biggestCapped >= 0) {
      svg.append(svgEl("text", { x: xAt(biggestCapped) + bw / 2 + 4, y: volTop + 10, class: "tick" },
        compact(pts[biggestCapped].v) + " (off scale)"));
    }

    // selective direct labels: the latest close, and the reference line's end when it has room
    const last = pts[lastI];
    const lastY = yAt(last.c);
    svg.append(svgEl("circle", { cx: xAt(lastI), cy: lastY, r: 4, class: "end-dot" }));
    svg.append(svgEl("text", { x: xAt(lastI) + 9, y: lastY + 4, class: "end-label" }, format(last.c, "money")));
    if (isNum(last.ref) && Math.abs(yAt(last.ref) - lastY) >= 16) {
      svg.append(svgEl("text", { x: xAt(lastI) + 9, y: yAt(last.ref) + 4, class: "end-label ref" }, format(last.ref, "money")));
    }

    // hover layer: a crosshair that snaps to the nearest bar, with one tooltip for every series
    const cross = svgEl("g", { visibility: "hidden" });
    const vline = svgEl("line", { y1: M.top, y2: bottom, class: "cross-line" });
    const refDot = svgEl("circle", { r: 4, class: "cross-dot ref" });
    const dot = svgEl("circle", { r: 4, class: "cross-dot" });
    cross.append(vline, refDot, dot);
    svg.append(cross);
    const overlay = svgEl("rect", { x: M.left, y: M.top, width: plotW, height: bottom - M.top, class: "overlay" });
    svg.append(overlay);
    host.append(svg);
    const tip = h("div", { class: "tooltip", "aria-hidden": "true", hidden: true });
    host.append(tip);

    const show = (i) => {
      i = Math.max(0, Math.min(n - 1, i));
      state.hoverIndex = i;
      const p = pts[i], x = xAt(i);
      vline.setAttribute("x1", x);
      vline.setAttribute("x2", x);
      for (const [node, v] of [[dot, p.c], [refDot, p.ref]]) {
        node.setAttribute("visibility", isNum(v) ? "visible" : "hidden");
        if (isNum(v)) { node.setAttribute("cx", x); node.setAttribute("cy", yAt(v)); }
      }
      cross.setAttribute("visibility", "visible");
      fillTooltip(tip, p, sr);
      tip.hidden = false;
      const scale = host.clientWidth / width;
      const px = x * scale;
      let left = px + 14;
      if (left + tip.offsetWidth > host.clientWidth - 4) left = px - 14 - tip.offsetWidth;
      tip.style.left = Math.max(4, left) + "px";
      tip.style.top = M.top * scale + 6 + "px";
    };
    const hide = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };

    overlay.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * width;
      show(Math.floor((x - M.left) / step));
    });
    overlay.addEventListener("pointerleave", hide);
    host.onkeydown = (e) => {
      const cur = state.hoverIndex == null ? n - 1 : state.hoverIndex;
      const moves = { ArrowLeft: cur - 1, ArrowRight: cur + 1, Home: 0, End: n - 1 };
      if (e.key in moves) { show(moves[e.key]); e.preventDefault(); }
      else if (e.key === "Escape") hide();
    };
    host.onfocus = () => show(state.hoverIndex == null ? n - 1 : state.hoverIndex);
    host.onblur = hide;
  }

  function fillTooltip(tip, p, sr) {
    tip.textContent = "";
    const when = sr.interval === "1m"
      ? formatDate(sr.session, { year: undefined }) + " · " + p.t + " ET"
      : formatDate(p.t, { weekday: "short" });
    const row = (cls, value, label) => h("div", { class: "tip-row" },
      h("span", { class: "key line " + cls }), h("strong", { text: value }), h("span", { class: "tip-label", text: label }));
    tip.append(h("div", { class: "tip-when", text: when }), row("key-price", format(p.c, "money"), "Close"));
    if (isNum(p.ref)) tip.append(row("key-ref", format(p.ref, "money"), sr.ref_label));
    tip.append(h("div", { class: "tip-extra",
      text: "Open " + format(p.o, "money") + " · High " + format(p.h, "money") + " · Low " + format(p.l, "money") }));
    let volume = "Volume " + compact(p.v || 0);
    if (isNum(p.vr)) volume += " · " + fixed(p.vr, 1) + "× its " + (sr.vr_label || "average");
    tip.append(h("div", { class: "tip-extra", text: volume }));
  }

  // ----------------------------------------------------------------- table

  function renderTable(sr) {
    const wrap = $("chart-table");
    const toggle = $("table-toggle");
    toggle.textContent = state.tableOpen ? "Hide table" : "Show table";
    toggle.setAttribute("aria-expanded", String(state.tableOpen));
    wrap.hidden = !state.tableOpen;
    wrap.textContent = "";
    if (!state.tableOpen || !sr || !sr.points.length) return;
    const intraday = sr.interval === "1m";
    const head = [intraday ? "Time (ET)" : "Date", "Open", "High", "Low", "Close", sr.ref_label, "Volume"];
    if (!intraday) head.push("Volume vs 20-day avg");
    const tbody = h("tbody");
    for (const p of sr.points.slice().reverse()) {
      const cells = [format(p.o, "money"), format(p.h, "money"), format(p.l, "money"), format(p.c, "money"),
        format(p.ref, "money"), compact(p.v || 0)];
      if (!intraday) cells.push(isNum(p.vr) ? fixed(p.vr, 2) + "×" : DASH);
      tbody.append(h("tr", {},
        h("th", { scope: "row", text: intraday ? p.t : formatDate(p.t) }),
        ...cells.map((c) => h("td", { class: "num", text: c }))));
    }
    wrap.append(h("table", { class: "data-table" },
      h("caption", { class: "sr-only", text: state.data.ticker + " trading points, " + WINDOWS[state.window] + ", newest first" }),
      h("thead", {}, h("tr", {}, ...head.map((x, i) => h("th", { scope: "col", class: i ? "num" : null, text: x })))),
      tbody));
  }

  // --------------------------------------------------------------- refresh

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function setStatus(text, kind) {
    const el = $("refresh-status");
    el.textContent = text || "";
    el.className = "status" + (kind ? " " + kind : "");
  }

  function updateRefreshButton() {
    const b = $("refresh-button");
    b.disabled = state.refreshing;
    b.textContent = state.refreshing ? "Refreshing…" : "Refresh";
    b.title = state.server
      ? "Fetch the latest data now (runs this asset's pipeline in UI\\asset\\)"
      : "Refresh needs the UI server: start it with UI\\link\\start-investing-ui.cmd";
  }

  async function detectServer() {
    state.server = false;
    if (location.protocol === "http:" || location.protocol === "https:") {
      try { state.server = (await fetch("api/status", { cache: "no-store" })).ok; } catch (e) { /* page served elsewhere */ }
    }
    updateRefreshButton();
    renderMenu();
    updateDeleteButton();
  }

  async function refresh() {
    if (state.refreshing) return;
    const ticker = state.ticker || assets()[0].ticker;
    if (!state.server) {
      setStatus("Refresh needs the UI server. Start it with UI\\link\\start-investing-ui.cmd; it opens this page at http://127.0.0.1:8765/.", "warn");
      return;
    }
    state.refreshing = true;
    updateRefreshButton();
    document.body.classList.add("is-refreshing");  // keep the current view, dimmed, while the update runs
    setStatus("Updating " + ticker + "…");
    try {
      const q = "?ticker=" + encodeURIComponent(ticker);
      const start = await fetch("api/refresh" + q, { method: "POST", headers: { "X-Requested-With": "investing-ui" } });
      if (!start.ok && start.status !== 409) throw new Error("the server answered " + start.status);
      let status;
      do {
        await sleep(POLL_MS);
        status = await (await fetch("api/status" + q, { cache: "no-store" })).json();
      } while (status.state === "running");
      if (status.state !== "done") throw new Error(status.message || "the update failed");
      await loadAssets();
      const data = await loadAsset(ticker);
      if (data && state.ticker === ticker) render(data);
      setStatus("Updated at " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), "ok");
      if (status.causes) watchReasons(ticker);
    } catch (e) {
      setStatus("Refresh failed: " + e.message, "error");
    } finally {
      state.refreshing = false;
      updateRefreshButton();
      document.body.classList.remove("is-refreshing");
    }
  }

  /** After a refresh or an add, the server compares the asset's analyst table with the
   *  kept one and, when there are new changes, looks up their reasons in the background.
   *  Follow that, and show the reasons when they arrive. Quiet when nothing is new. */
  async function watchReasons(ticker, onlyIfRunning) {
    if (state.watching === ticker) return;
    state.watching = ticker;
    const q = "?ticker=" + encodeURIComponent(ticker) + "&job=causes";
    try {
      let status, announced = false, first = true;
      for (;;) {
        status = await (await fetch("api/status" + q, { cache: "no-store" })).json();
        if (first && onlyIfRunning && status.state !== "running") return;
        first = false;
        if (status.state !== "running") break;
        if (status.phase === "searching" && !announced) {
          announced = true;
          state.searching = ticker;
          if (state.ticker === ticker && state.data) renderAnalystTable(state.data.analyst_actions);
          const n = status.to_explain;
          setStatus("Looking up the reasons behind " + n + " new analyst " + (n === 1 ? "change" : "changes") +
            " for " + ticker + "\u2026 This takes a few minutes.");
        }
        await sleep(announced ? 5000 : 1500);
      }
      state.searching = null;
      if (status.state === "error") {
        setStatus("Couldn't look up the reasons behind new analyst changes for " + ticker + ": " + (status.message || "unknown error"), "warn");
      } else if (status.explained) {
        const data = await loadAsset(ticker);
        if (data && state.ticker === ticker) render(data);
        setStatus("Added the reasons behind " + status.explained + " new analyst " +
          (status.explained === 1 ? "change" : "changes") + " for " + ticker + ".", "ok");
      } else if (announced && state.ticker === ticker && state.data) {
        renderAnalystTable(state.data.analyst_actions);
      }
    } catch (e) {
      state.searching = null;  // the server stopped; the next refresh tries again
    } finally {
      state.watching = null;
    }
  }

  function showNotice(title, text) {
    $("notice-title").textContent = title;
    $("notice-text").textContent = text || "";
    $("notice").hidden = false;
  }

  /** Add an asset: the server runs UI/pipeline/new_page.py (no AI), and we wait for its report. */
  async function addAsset(raw) {
    const ticker = String(raw || "").trim().toUpperCase();
    if (!TICKER_RE.test(ticker)) {
      setStatus("Enter a ticker like NVDA, BRK-B or TEVA.TA.", "warn");
      return;
    }
    if ((window.INVESTING_ASSETS || []).some((a) => a.ticker === ticker)) {
      closeMenu();
      setStatus(ticker + " is already in Your assets.");
      go(ticker, "overview");
      return;
    }
    if (!state.server) {
      setStatus("Adding needs the UI server: start it with UI\\link\\start-investing-ui.cmd.", "warn");
      return;
    }
    state.adding = ticker;
    state.addOpen = false;
    renderMenu();
    closeMenu();
    const started = Date.now();
    setStatus("Adding " + ticker + ": building the page…");
    try {
      const q = "?ticker=" + encodeURIComponent(ticker);
      const res = await fetch("api/assets" + q, { method: "POST", headers: { "X-Requested-With": "investing-ui" } });
      const body = await res.json().catch(() => ({}));
      if (res.status === 409 && body.registered) {
        await loadAssets();
        setStatus(ticker + " is already in Your assets.");
        go(ticker, "overview");
        return;
      }
      if (!res.ok) throw new Error(body.error || "the server answered " + res.status);
      let status;
      do {
        await sleep(2000);
        status = await (await fetch("api/status" + q + "&job=add", { cache: "no-store" })).json();
        setStatus("Adding " + ticker + ": building the page (" + Math.round((Date.now() - started) / 1000) + " s)…");
      } while (status.state === "running");
      await loadAssets();
      if (status.added) {
        go(ticker, "overview");
        setStatus(ticker + " added.", "ok");
        showNotice(ticker + " added", status.message);
        if (status.causes) watchReasons(ticker);
      } else {
        setStatus("Couldn't add " + ticker + "; see the note below.", "error");
        showNotice("Couldn't add " + ticker, status.message);
      }
    } catch (e) {
      setStatus("Adding " + ticker + " failed: " + e.message, "error");
    } finally {
      state.adding = null;
      renderMenu();
    }
  }

  function updateDeleteButton() {
    const b = $("delete-asset");
    if (!state.ticker) return;
    b.textContent = state.deleting === state.ticker ? "Deleting…" : "Delete " + state.ticker;
    b.disabled = !state.server || Boolean(state.deleting);
    b.title = state.server
      ? "Delete " + state.ticker + " from Your assets"
      : "Deleting needs the UI server: start it with UI\\link\\start-investing-ui.cmd";
  }

  function showEmpty() {
    state.ticker = null;
    state.data = null;
    state.view = "overview";
    state.shownView = null;
    $("asset-view").hidden = true;
    $("missing-state").hidden = true;
    $("empty-state").hidden = false;
    document.title = "Investing";
    history.replaceState(null, "", location.pathname + location.search);
  }

  /** Delete an asset. The server archives its folder in UI/asset/_deleted/, so it can be restored. */
  async function deleteAsset(ticker) {
    if (!state.server) {
      setStatus("Deleting needs the UI server: start it with UI\\link\\start-investing-ui.cmd.", "warn");
      return;
    }
    const sure = window.confirm("Delete " + ticker + " from Your assets?");
    if (!sure) return;
    state.deleting = ticker;
    renderMenu();
    updateDeleteButton();
    try {
      const res = await fetch("api/assets?ticker=" + encodeURIComponent(ticker),
        { method: "DELETE", headers: { "X-Requested-With": "investing-ui" } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body.ok) throw new Error(body.error || "the server answered " + res.status);
      if (window.INVESTING_DATA) delete window.INVESTING_DATA[ticker];
      await loadAssets();
      if (state.ticker === ticker) showEmpty();
      setStatus(ticker + " deleted.", "ok");
    } catch (e) {
      setStatus("Deleting " + ticker + " failed: " + e.message, "error");
    } finally {
      state.deleting = null;
      renderMenu();
      updateDeleteButton();
    }
  }

  /** Pick up files the updater wrote on its own (e.g. a scheduled run). */
  async function reread() {
    if (state.refreshing || !state.ticker) return;
    await loadAssets();
    const data = await loadAsset(state.ticker);
    if (data && (!state.data || data.updated_at !== state.data.updated_at)) render(data);
  }

  // ----------------------------------------------------------------- theme

  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
    $("theme-button").textContent = "Theme: " + theme.charAt(0).toUpperCase() + theme.slice(1);
    try {
      if (theme === "auto") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, theme);
    } catch (e) { /* storage unavailable: the choice lasts for this visit */ }
  }

  // ------------------------------------------------------------------ init

  function init() {
    wireMenu();
    $("refresh-button").addEventListener("click", refresh);
    $("notice-close").addEventListener("click", () => { $("notice").hidden = true; });
    $("delete-asset").addEventListener("click", () => { if (state.ticker) deleteAsset(state.ticker); });
    $("theme-button").addEventListener("click", () => {
      const order = ["auto", "light", "dark"];
      const now = document.documentElement.getAttribute("data-theme") || "auto";
      applyTheme(order[(order.indexOf(now) + 1) % order.length]);
    });
    applyTheme(document.documentElement.getAttribute("data-theme") || "auto");
    for (const b of document.querySelectorAll("[data-window]")) {
      b.addEventListener("click", () => {
        state.window = b.dataset.window;
        state.hoverIndex = null;
        if (state.data) {
          renderWindow();
          history.replaceState(null, "", hashFor(state.ticker, "graphs"));  // no history entry per window
        }
      });
    }
    $("table-toggle").addEventListener("click", () => {
      state.tableOpen = !state.tableOpen;
      if (state.data) renderTable(state.data.series[state.window]);
    });

    let lastWidth = 0;
    new ResizeObserver(() => {
      const w = $("chart").clientWidth;
      if (state.data && state.view === "graphs" && w > 0 && Math.abs(w - lastWidth) > 1) {
        lastWidth = w;
        drawChart(state.data.series[state.window]);
      }
    }).observe($("chart"));

    window.addEventListener("hashchange", route);
    setInterval(reread, REREAD_MS);

    detectServer();
    loadAssets().then(route);
  }

  init();
})();
