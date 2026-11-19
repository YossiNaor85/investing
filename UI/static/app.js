/* Investing UI: the "Your assets" picker, three price windows, and the
   ratio panels.
   Data comes from data/<TICKER>.js, written by UI/iren_page/update_iren_page.py.
   When the page is served by UI/server.py, the Refresh button runs that updater. */
(() => {
  "use strict";

  const SCHEMA = 1;                 // the data format this script reads (UI/pipeline/asset_page.py SCHEMA)
  const REREAD_MS = 5 * 60 * 1000;  // re-read the data files this often
  const POLL_MS = 1000;             // status polling while a refresh runs
  const WINDOWS = { "1Y": "1 year", "3M": "3 months", "1D": "1 day" };
  const HIGH_VOLUME = 1.5;          // same threshold as the updater
  const TICKER_RE = /^[A-Z0-9.\-]{1,12}$/;
  const THEME_KEY = "investing-theme";
  const MINUS = "−";
  const DASH = "—";
  const SVG_NS = "http://www.w3.org/2000/svg";

  const state = {
    ticker: null,
    window: "1Y",
    data: null,
    currency: "USD",
    tableOpen: false,
    hoverIndex: null,
    server: false,
    refreshing: false,
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
      item.addEventListener("click", () => { closeMenu(); selectAsset(a.ticker); });
      menu.append(item);
    }
    menu.append(h("div", { class: "menu-foot", text: "Add an asset with the asset-page skill: /asset-page TICKER" }));
  }

  function menuItems() { return Array.from($("assets-menu").querySelectorAll(".menu-item")); }

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
    const [t, w] = decodeURIComponent(location.hash.replace(/^#/, "")).split("/");
    const ticker = (t || "").toUpperCase();
    return { ticker: TICKER_RE.test(ticker) ? ticker : null, window: WINDOWS[w] ? w : null };
  }

  function writeHash() {
    const next = "#" + state.ticker + "/" + state.window;
    if (location.hash !== next) history.replaceState(null, "", next);
  }

  async function selectAsset(ticker, win) {
    state.ticker = ticker;
    if (win) state.window = win;
    const data = await loadAsset(ticker);
    if (!data) { showMissing(ticker); return; }
    render(data);
    writeHash();
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
    document.title = data.ticker + " · Investing";
    renderHead(data);
    renderKpis(data.kpis);
    renderWindow();
    renderGroups($("ratios"), data.ratios);
    renderGroups($("econ"), data.econometrics);
    renderFooter(data);
  }

  function renderHead(d) {
    $("asset-title").textContent = d.name;
    $("asset-sub").textContent = [d.ticker, d.exchange, d.currency, d.classification].filter(Boolean).join(" · ");
    $("asset-note").textContent = d.note || "";
    $("asset-note").hidden = !d.note;
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

  function renderGroups(host, groups) {
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
        rows));
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
      svg.append(svgEl("text", { x: M.left + plotW - 4, y: y - 6, class: "ref-label", "text-anchor": "end" },
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
      ? "Fetch the latest data now (runs UI\\iren_page\\update_iren_page.py)"
      : "Refresh needs the UI server: start it with UI\\link\\start-investing-ui.cmd";
  }

  async function detectServer() {
    state.server = false;
    if (location.protocol === "http:" || location.protocol === "https:") {
      try { state.server = (await fetch("api/status", { cache: "no-store" })).ok; } catch (e) { /* page served elsewhere */ }
    }
    updateRefreshButton();
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
    } catch (e) {
      setStatus("Refresh failed: " + e.message, "error");
    } finally {
      state.refreshing = false;
      updateRefreshButton();
      document.body.classList.remove("is-refreshing");
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
        if (state.data) { renderWindow(); writeHash(); }
      });
    }
    $("table-toggle").addEventListener("click", () => {
      state.tableOpen = !state.tableOpen;
      if (state.data) renderTable(state.data.series[state.window]);
    });

    let lastWidth = 0;
    new ResizeObserver(() => {
      const w = $("chart").clientWidth;
      if (state.data && Math.abs(w - lastWidth) > 1) {
        lastWidth = w;
        drawChart(state.data.series[state.window]);
      }
    }).observe($("chart"));

    window.addEventListener("hashchange", () => {
      const r = parseHash();
      if (r.ticker && (r.ticker !== state.ticker || (r.window && r.window !== state.window))) selectAsset(r.ticker, r.window);
    });
    setInterval(reread, REREAD_MS);

    detectServer();
    loadAssets().then(() => {
      const r = parseHash();
      if (r.ticker) selectAsset(r.ticker, r.window);
    });
  }

  init();
})();
