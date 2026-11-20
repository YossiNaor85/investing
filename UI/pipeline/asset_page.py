r"""Shared engine for the asset pages of the investing UI.

Every followed asset has a folder UI/asset/<slug>_page/ containing:

    config.json                 the asset's settings: comparison series and why
    update_<slug>_page.py       its pipeline entry point, which calls main() below
    analyst_table.json          the analyst table with each change's reason (stocks).
                                UI/pipeline/rating_causes.py and the
                                rating_change_cause_searcher skill keep it; the
                                pipeline only reads it.

The pipeline fetches prices and company data from Yahoo Finance (through
yfinance), computes financial ratios and econometric measures, and writes:

    UI/data/<TICKER>.js      what UI/index.html reads. It's a <script> file, so the
                             page also works when opened straight from disk.
    UI/data/<TICKER>.json    the same data as plain JSON
    UI/data/assets.js        My watchlist, built from UI/assets.json

The data format is described in .claude/skills/asset-page/references/page-contract.md.
A change here changes every page, so keep UI/static/app.js in step with it.
Per-asset changes belong in that asset's customize() function instead.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

SCHEMA = 1           # version of the data format; UI/static/app.js checks it
TRADING_DAYS = 252
HIGH_VOLUME = 1.5    # volume at or above this multiple of its 20-day average counts as high

MARKET_LABELS = {"SPY": "S&P 500 (SPY)", "QQQ": "Nasdaq 100 (QQQ)", "IWM": "Russell 2000 (IWM)"}
EXCHANGES = {
    "NMS": "Nasdaq", "NGM": "Nasdaq", "NCM": "Nasdaq", "NYQ": "NYSE", "ASE": "NYSE American",
    "PCX": "NYSE Arca", "BTS": "Cboe", "TLV": "Tel Aviv", "CCC": "Crypto",
}
CURRENCY_NOTES = {"ILA": "agorot, 1/100 of a shekel", "GBp": "pence, 1/100 of a pound", "ZAc": "cents"}

Customize = Callable[[dict, dict], Optional[dict]]


# ----------------------------------------------------------------- helpers

def number(value) -> Optional[float]:
    """A finite float, or None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def price(value) -> Optional[float]:
    v = number(value)
    return None if v is None else round(v, 4)


def ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def change(a: Optional[float], b: Optional[float]) -> Optional[float]:
    r = ratio(a, b)
    return None if r is None else r - 1


def epoch_to_date(value) -> Optional[str]:
    v = number(value)
    if v is None:
        return None
    return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d")


def item(label: str, value, fmt: str, note: Optional[str] = None, hint: Optional[str] = None) -> dict:
    out = {"label": label, "value": value, "fmt": fmt}
    if note:
        out["note"] = note
    if hint:
        out["hint"] = hint
    return out


def clean(obj):
    """Replace NaN and infinity with None so the output is valid JSON."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file, so the page never reads a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def slug(ticker: str) -> str:
    """Folder-safe name for a ticker: BRK-B -> brk_b, TEVA.TA -> teva_ta."""
    return re.sub(r"[^a-z0-9]+", "_", ticker.lower()).strip("_")


def short_label(label: str) -> str:
    """'S&P 500 (SPY)' -> 'S&P 500'."""
    return label.split(" (")[0]


# --------------------------------------------------------------- registry

def load_registry(ui_dir: Path) -> list:
    """The followed assets (My watchlist), from UI/assets.json. The page sorts them by domain, then A to Z."""
    path = ui_dir / "assets.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8-sig")).get("assets", [])


def save_registry(ui_dir: Path, assets: list) -> None:
    write_atomic(ui_dir / "assets.json", json.dumps({"assets": assets}, indent=2, ensure_ascii=False) + "\n")


def write_assets(ui_dir: Path) -> None:
    """Rewrite UI/data/assets.js, the list behind My watchlist."""
    data_dir = ui_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for a in load_registry(ui_dir):
        ticker = a["ticker"]
        entry = {"ticker": ticker, "name": a.get("name") or ticker, "has_data": False}
        path = data_dir / f"{ticker}.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8-sig"))
            q = d.get("quote") or {}
            domain = d.get("domain") or (d.get("classification") or "").replace("Yahoo: ", "", 1) or None
            entry.update(name=d.get("name") or entry["name"], has_data=True, domain=domain, price=q.get("price"),
                         change_pct=q.get("change_pct"), currency=d.get("currency"), updated_at=d.get("updated_at"))
        out.append(entry)
    write_atomic(data_dir / "assets.js",
                 "window.INVESTING_ASSETS = " + json.dumps(out, ensure_ascii=False, allow_nan=False) + ";\n")


# ---------------------------------------------------------------- fetching

def fetch_history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """Price history with a few retries, because Yahoo throttles bursts."""
    error: Optional[Exception] = None
    for attempt in range(3):
        try:
            frame = yf.Ticker(symbol).history(period=period, interval=interval)
            frame = frame.dropna(subset=["Close"])
            if not frame.empty:
                return frame
            error = RuntimeError("no rows returned")
        except Exception as exc:  # network errors and throttling surface here
            error = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{symbol} {period}/{interval}: {error}")


def fetch_info(symbol: str) -> dict:
    for attempt in range(3):
        try:
            info = yf.Ticker(symbol).info
            if info and len(info) > 1:
                return info
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
    return {}


def earnings_dates(symbol: str, info: dict) -> tuple:
    """(next earnings date, latest earnings date) as ISO strings, when known."""
    today = date.today().isoformat()
    candidates = []
    try:
        for d in (yf.Ticker(symbol).calendar or {}).get("Earnings Date") or []:
            candidates.append(pd.Timestamp(d).strftime("%Y-%m-%d"))
    except Exception:
        pass
    for key in ("earningsTimestampStart", "earningsTimestamp"):
        d = epoch_to_date(info.get(key))
        if d:
            candidates.append(d)
    upcoming = sorted(d for d in candidates if d >= today)
    past = sorted(d for d in candidates if d < today)
    return (upcoming[0] if upcoming else None, past[-1] if past else None)


# ------------------------------------------------------------ price series

def daily_window(hist: pd.DataFrame, days: int, ma_len: int) -> dict:
    """Daily bars for the last `days` calendar days, with a moving average and
    each day's volume as a multiple of the previous 20 sessions' average."""
    close = hist["Close"]
    volume = hist["Volume"].astype(float)
    ma = close.rolling(ma_len).mean()
    vol_avg = volume.rolling(20).mean().shift(1)
    keep = hist.index >= hist.index[-1] - pd.Timedelta(days=days)
    points = []
    for ts in hist.index[keep]:
        avg = vol_avg[ts]
        points.append({
            "t": ts.strftime("%Y-%m-%d"),
            "o": price(hist.at[ts, "Open"]),
            "h": price(hist.at[ts, "High"]),
            "l": price(hist.at[ts, "Low"]),
            "c": price(close[ts]),
            "v": int(volume[ts]),
            "ref": price(ma[ts]),
            "vr": round(float(volume[ts] / avg), 2) if pd.notna(avg) and avg > 0 else None,
        })
    return {"interval": "1d", "ref_label": f"{ma_len}-day average",
            "vr_label": "20-day average", "points": points}


def last_session(hist_1m: pd.DataFrame) -> pd.DataFrame:
    last_day = hist_1m.index[-1].date()
    return hist_1m[hist_1m.index.date == last_day]


def intraday_window(day: pd.DataFrame, prev_close: Optional[float]) -> dict:
    """One-minute bars of the latest session, with VWAP: the volume-weighted
    average price that institutions benchmark their executions against."""
    typical = (day["High"] + day["Low"] + day["Close"]) / 3
    volume = day["Volume"].astype(float)
    vwap = (typical * volume).cumsum() / volume.cumsum().replace(0, np.nan)
    points = []
    for ts in day.index:
        points.append({
            "t": ts.strftime("%H:%M"),
            "o": price(day.at[ts, "Open"]),
            "h": price(day.at[ts, "High"]),
            "l": price(day.at[ts, "Low"]),
            "c": price(day.at[ts, "Close"]),
            "v": int(volume[ts]),
            "ref": price(vwap[ts]),
        })
    return {"interval": "1m", "session": day.index[-1].strftime("%Y-%m-%d"),
            "ref_label": "VWAP", "prev_close": price(prev_close), "points": points}


# --------------------------------------------------------- econometrics

def aligned_returns(a: pd.Series, b: pd.Series) -> pd.DataFrame:
    """Daily returns of a and b, on the dates both have a close."""
    def by_date(s: pd.Series) -> pd.Series:
        s = s.copy()
        s.index = [ts.date() for ts in s.index]
        return s[~pd.Index(s.index).duplicated(keep="last")]
    both = pd.concat([by_date(a), by_date(b)], axis=1, join="inner").dropna()
    return both.pct_change().dropna()


def beta(rets: pd.DataFrame, n: int) -> Optional[float]:
    if len(rets) < n:
        return None
    a = rets.iloc[-n:, 0].to_numpy()
    m = rets.iloc[-n:, 1].to_numpy()
    var_m = np.var(m, ddof=1)
    if not var_m:
        return None
    return float(np.cov(a, m, ddof=1)[0, 1] / var_m)


def correlation(rets: pd.DataFrame, n: int) -> Optional[float]:
    if len(rets) < n:
        return None
    return float(np.corrcoef(rets.iloc[-n:, 0], rets.iloc[-n:, 1])[0, 1])


def change_over(close: pd.Series, n: int) -> Optional[float]:
    if len(close) <= n:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1)


def window_change(close: pd.Series, days: int) -> Optional[float]:
    """Change since the first close inside the last `days` calendar days, which
    is the same base the page's price windows use."""
    base = close[close.index >= close.index[-1] - pd.Timedelta(days=days)]
    if len(base) < 2:
        return None
    return float(close.iloc[-1] / base.iloc[0] - 1)


def ytd_change(close: pd.Series) -> Optional[float]:
    before = close[close.index.year < close.index[-1].year]
    if before.empty:
        return None
    return float(close.iloc[-1] / before.iloc[-1] - 1)


def volatility(close: pd.Series, n: int) -> Optional[float]:
    r = close.pct_change().dropna()
    if len(r) < n:
        return None
    return float(r.iloc[-n:].std(ddof=1) * math.sqrt(TRADING_DAYS))


def session_moves(day: pd.DataFrame) -> dict:
    """Moves inside the latest session: the first 15 and 90 minutes (the doc's
    institutional window), the last 30 minutes, and the close against VWAP."""
    times = day.index.strftime("%H:%M")
    open_ = float(day["Open"].iloc[0])
    last = float(day["Close"].iloc[-1])

    def close_before(hhmm: str) -> Optional[float]:
        sel = day[times < hhmm]
        return float(sel["Close"].iloc[-1]) if len(sel) else None

    typical = (day["High"] + day["Low"] + day["Close"]) / 3
    vol = day["Volume"].astype(float)
    vwap = float((typical * vol).sum() / vol.sum()) if vol.sum() else None
    complete = times[-1] >= "15:59"
    return {
        "first15": change(close_before("09:45"), open_) if times[-1] >= "09:45" else None,
        "first90": change(close_before("11:00"), open_) if times[-1] >= "11:00" else None,
        "last30": change(last, close_before("15:30")) if complete else None,
        "vs_vwap": change(last, vwap),
    }


# ---------------------------------------------------------- ratio groups

def company_ratios(info: dict, current: float, ticker: str) -> list:
    """Yahoo's company figures. Cross-check them with SEC filings later."""
    g = lambda key: number(info.get(key))  # noqa: E731
    ebitda = g("ebitda")
    trailing_pe = g("trailingPE")
    cash, debt = g("totalCash"), g("totalDebt")
    target = g("targetMeanPrice")
    next_earnings, last_earnings = earnings_dates(ticker, info)
    rec_text = None
    if info.get("recommendationKey") and g("recommendationMean") is not None:
        rec_text = (f"{str(info['recommendationKey']).replace('_', ' ').capitalize()} "
                    f"({g('recommendationMean'):.2f} on a 1–5 scale, 1 = strong buy)")
    target_range = None
    if g("targetLowPrice") is not None and g("targetHighPrice") is not None:
        target_range = [g("targetLowPrice"), g("targetHighPrice")]
    dividend = g("dividendYield")  # Yahoo gives this one in percent
    return [
        {"title": "Valuation", "items": [
            item("Market cap", g("marketCap"), "money_compact"),
            item("Enterprise value", g("enterpriseValue"), "money_compact"),
            item("Price / sales (TTM)", g("priceToSalesTrailing12Months"), "x"),
            item("EV / revenue", g("enterpriseToRevenue"), "x"),
            item("EV / EBITDA", g("enterpriseToEbitda") if (ebitda or 0) > 0 else None, "x",
                 note="n/m: EBITDA is negative" if ebitda is not None and ebitda <= 0 else None),
            item("P/E, trailing", trailing_pe, "x",
                 note="n/m: loss over the last 12 months" if trailing_pe is None and (g("trailingEps") or 0) < 0 else None),
            item("P/E, forward", g("forwardPE"), "x"),
            item("Price / book", g("priceToBook"), "x"),
            item("Dividend yield", dividend / 100 if dividend is not None else None, "pct"),
        ]},
        {"title": "Profitability (TTM)", "items": [
            item("Gross margin", g("grossMargins"), "pct"),
            item("EBITDA margin", g("ebitdaMargins"), "pct"),
            item("Operating margin", g("operatingMargins"), "pct"),
            item("Net margin", g("profitMargins"), "pct"),
            item("Return on equity", g("returnOnEquity"), "pct"),
            item("Return on assets", g("returnOnAssets"), "pct"),
        ]},
        {"title": "Growth and scale", "items": [
            item("Revenue (TTM)", g("totalRevenue"), "money_compact"),
            item("Revenue growth (latest quarter, y/y)", g("revenueGrowth"), "pct_signed"),
            item("Earnings growth (latest quarter, y/y)", g("earningsGrowth"), "pct_signed"),
            item("EBITDA (TTM)", ebitda, "money_compact"),
        ]},
        {"title": "Balance sheet and cash flow", "items": [
            item("Cash", cash, "money_compact"),
            item("Total debt", debt, "money_compact"),
            item("Net debt", debt - cash if debt is not None and cash is not None else None, "money_compact"),
            item("Debt / equity", g("debtToEquity") / 100 if g("debtToEquity") is not None else None, "x"),
            item("Current ratio", g("currentRatio"), "x"),
            item("Quick ratio", g("quickRatio"), "x"),
            item("Operating cash flow (TTM)", g("operatingCashflow"), "money_compact"),
            item("Free cash flow (TTM)", g("freeCashflow"), "money_compact"),
        ]},
        {"title": "Shares and ownership", "items": [
            item("Shares outstanding", g("sharesOutstanding"), "int_compact"),
            item("Float", g("floatShares"), "int_compact"),
            item("Short interest, % of float", g("shortPercentOfFloat"), "pct"),
            item("Days to cover", g("shortRatio"), "days"),
            item("Held by institutions", g("heldPercentInstitutions"), "pct"),
            item("Held by insiders", g("heldPercentInsiders"), "pct"),
        ]},
        {"title": "Analysts", "id": "analysts", "items": [
            item("Consensus", rec_text, "text"),
            item("Analysts", g("numberOfAnalystOpinions"), "int"),
            item("Mean price target", target, "money"),
            item("Upside to mean target", change(target, current), "pct_signed"),
            item("Target range", target_range, "money_range"),
        ]},
        {"title": "Calendar", "items": [
            item("Next earnings", next_earnings, "date"),
            item("Latest earnings", last_earnings, "date"),
            item("Latest quarter end", epoch_to_date(info.get("mostRecentQuarter")), "date"),
            item("Fiscal year end", epoch_to_date(info.get("lastFiscalYearEnd")), "date"),
        ]},
    ]


def fund_ratios(info: dict) -> list:
    """ETF and fund figures. Yahoo mixes units: some are percents, some fractions."""
    g = lambda key: number(info.get(key))  # noqa: E731
    pct = lambda key: g(key) / 100 if g(key) is not None else None  # noqa: E731
    return [
        {"title": "Fund", "items": [
            item("Category", info.get("category"), "text"),
            item("Fund family", info.get("fundFamily"), "text"),
            item("Total assets", g("totalAssets"), "money_compact"),
            item("Expense ratio", pct("netExpenseRatio"), "pct"),
            item("Yield", g("yield"), "pct"),
            item("NAV", g("navPrice"), "money"),
        ]},
        {"title": "Fund returns (Yahoo)", "items": [
            item("Year to date", pct("ytdReturn"), "pct_signed"),
            item("3-year average", g("threeYearAverageReturn"), "pct_signed"),
            item("5-year average", g("fiveYearAverageReturn"), "pct_signed"),
            item("Beta, 3 years", g("beta3Year"), "num"),
        ]},
        {"title": "Valuation of holdings", "items": [
            item("P/E, trailing", g("trailingPE"), "x"),
        ]},
    ]


def basic_ratios(info: dict) -> list:
    """For assets without company or fund figures (crypto, indexes)."""
    return [{"title": "Asset", "items": [
        item("Market cap", number(info.get("marketCap")), "money_compact"),
        item("Type", (info.get("quoteType") or "").capitalize() or None, "text"),
    ]}]


# -------------------------------------------- analyst rating changes + why

# The analyst table is kept in the asset's folder, in this file, with the firm's reason
# for each change. It's the table as of the last search for reasons: on Refresh, Yahoo's
# table is compared with it, and only new changes go to the rating_change_cause_searcher
# skill (UI/pipeline/rating_causes.py keeps the file). The update below only reads it.
# A change is a new rating or a new price target; a plain reiteration needs no reason.
KEPT_TABLE = "analyst_table.json"
FACTS = ("date", "firm", "action", "rating", "previous", "prior_target", "target", "rating_changed", "target_changed")
ACTIONS = {"up": "upgrade", "down": "downgrade", "init": "new coverage", "main": "maintained", "reit": "reiterated"}


def _text(value) -> str:
    """A cell as text: '' for None and NaN."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def needs_reason(row: dict) -> bool:
    """True when the firm changed its rating or its price target."""
    return bool(row.get("rating_changed") or row.get("target_changed"))


def rating_changes(ticker: str, days: int = 365) -> Optional[dict]:
    """Yahoo's analyst updates of the past `days` days, newest first, as {"since", "rows"}.
    A row's id, "<date>|<firm>|<rating>|<previous>", keys it in the kept table.
    None when Yahoo has none."""
    try:
        df = yf.Ticker(ticker).upgrades_downgrades
    except Exception:
        return None
    if df is None or df.empty:
        return None
    index = pd.to_datetime(df.index)
    if index.tz is not None:
        index = index.tz_convert(None)
    since = pd.Timestamp.now() - pd.Timedelta(days=days)
    df = df.set_axis(index)
    df = df[df.index >= since].sort_index(ascending=False)
    rows = []
    for ts, r in df.iterrows():
        firm, rating, previous = _text(r.get("Firm")), _text(r.get("ToGrade")), _text(r.get("FromGrade"))
        action = _text(r.get("Action"))
        target = number(r.get("currentPriceTarget")) or None      # 0 means none
        prior = number(r.get("priorPriceTarget")) or None
        rows.append({
            "id": f"{ts:%Y-%m-%d}|{firm}|{rating}|{previous}",
            "date": f"{ts:%Y-%m-%d}",
            "firm": firm,
            "action": ACTIONS.get(action.lower(), action or None),
            "rating": rating or None,
            "previous": previous or None,
            "prior_target": prior,
            "target": target,
            "rating_changed": rating != previous,  # an upgrade, downgrade or new coverage
            "target_changed": bool(target and prior and target != prior),
        })
    return {"since": f"{since:%Y-%m-%d}", "rows": rows}


def load_kept(path: Path) -> dict:
    """An asset's kept analyst table as {id: row}; empty when there's none yet."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")).get("rows") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def analyst_actions(ticker: str, kept_path: Path) -> Optional[dict]:
    """Analyst updates of the past year, newest first. Each change of rating or target
    gets its reason from the kept table. Nothing is searched here, so an update stays
    quick and calls no AI. Changes not looked into yet count as pending."""
    table = rating_changes(ticker)
    kept = load_kept(kept_path)
    if not table and not kept:
        return None
    since = table["since"] if table else f"{pd.Timestamp.now() - pd.Timedelta(days=365):%Y-%m-%d}"
    by_id = {r["id"]: r for r in (table["rows"] if table else [])}
    # Yahoo sometimes leaves a recent row out of an answer; the kept table still has it.
    for cid, k in kept.items():
        if cid not in by_id and (k.get("date") or "") >= since:
            by_id[cid] = dict(k, id=cid)
    rows = []
    for source_row in sorted(by_id.values(), key=lambda r: r["date"], reverse=True):  # stable: keeps Yahoo's order within a day
        row = {k: source_row.get(k) for k in FACTS}
        if needs_reason(row):
            entry = kept.get(source_row["id"]) or {}
            row["searched"] = bool(entry.get("searched"))
            if row["searched"]:
                row.update(why=entry.get("cause"), why_basis=entry.get("basis"),
                           why_source=entry.get("source"), why_url=entry.get("url"))
        rows.append(row)
    return {"since": since, "rows": rows,
            "changes": sum(1 for r in rows if needs_reason(r)),
            "pending": sum(1 for r in rows if r.get("searched") is False)}


# ------------------------------------------------------------------- build

def build(cfg: dict, customize: Optional[Customize] = None, page_dir: Optional[Path] = None) -> dict:
    """The page's data. page_dir is the asset's folder, where its analyst table is kept."""
    ticker = cfg["ticker"]
    market = cfg.get("market", "SPY")
    compare = dict(cfg.get("compare") or {})
    if market not in compare:
        compare = {market: MARKET_LABELS.get(market, market), **compare}
    why = cfg.get("why") or {}
    market_label = compare[market]

    warnings = []
    info = fetch_info(ticker)
    if not info:
        warnings.append("Company data (ratios) could not be loaded from Yahoo this time.")
    kind = (info.get("quoteType") or "EQUITY").upper()
    currency = info.get("currency") or "USD"
    if currency != "USD":
        unit = f" ({CURRENCY_NOTES[currency]})" if currency in CURRENCY_NOTES else ""
        warnings.append(f"Prices are in {currency}{unit}. Yahoo's company figures for non-US listings "
                        "can be in another currency; check them before comparing.")

    hist = fetch_history(ticker, "2y", "1d")
    close = hist["Close"]
    day = None
    try:
        day = last_session(fetch_history(ticker, "5d", "1m"))
    except RuntimeError as exc:
        warnings.append(f"No intraday data: {exc}")
    compare_close = {}
    for symbol in compare:
        try:
            compare_close[symbol] = fetch_history(symbol, "2y", "1d")["Close"]
        except RuntimeError as exc:
            warnings.append(f"No history for {symbol}: {exc}")

    # ---- price windows
    series = {"1Y": daily_window(hist, 365, 50), "3M": daily_window(hist, 92, 20)}
    if day is not None and len(day):
        session = day.index[-1].date()
        earlier = close[[ts.date() < session for ts in close.index]]
        series["1D"] = intraday_window(day, float(earlier.iloc[-1]) if len(earlier) else None)
        # The official close comes from the closing auction, so it can differ from the last minute bar.
        if session == close.index[-1].date() and day.index[-1].strftime("%H:%M") >= "15:59":
            series["1D"]["session_close"] = price(close.iloc[-1])

    # ---- quote
    last_close = float(close.iloc[-1])
    current = number(info.get("currentPrice")) or number(info.get("regularMarketPrice")) or last_close
    prev = number(info.get("previousClose")) or (float(close.iloc[-2]) if len(close) > 1 else None)
    quote = {
        "price": price(current),
        "previous_close": price(prev),
        "change": price(current - prev) if prev else None,
        "change_pct": change(current, prev),
        "market_state": info.get("marketState"),
        "last_close_date": close.index[-1].strftime("%Y-%m-%d"),
    }
    state = (info.get("marketState") or "").upper()
    for prefix, key, label in (("PRE", "preMarketPrice", "Pre-market"), ("POST", "postMarketPrice", "After hours")):
        ext = number(info.get(key))
        if state.startswith(prefix) and ext:
            quote["extended"] = {"label": label, "price": price(ext), "change_pct": change(ext, current)}

    # ---- econometrics
    mkt = aligned_returns(close, compare_close[market]) if market in compare_close else pd.DataFrame()
    b = {n: beta(mkt, n) for n in (10, 21, 63, 252)} if len(mkt) else {}
    year = hist[hist.index >= hist.index[-1] - pd.Timedelta(days=365)]
    max_dd = float((year["Close"] / year["Close"].cummax() - 1).min())
    from_high = float(year["Close"].iloc[-1] / year["High"].max() - 1)
    ma50 = number(close.rolling(50).mean().iloc[-1])
    ma200 = number(close.rolling(200).mean().iloc[-1])
    volume = hist["Volume"].astype(float)
    vol_vs_avg = ratio(float(volume.iloc[-1]), float(volume.iloc[-21:-1].mean())) if len(volume) > 21 else None
    dollar_vol = float((close * volume).iloc[-20:].mean())

    econ = [
        {"title": "Returns", "items": [
            item("1 day", change_over(close, 1), "pct_signed"),
            item("1 week", change_over(close, 5), "pct_signed"),
            item("1 month", change_over(close, 21), "pct_signed"),
            item("3 months", window_change(close, 92), "pct_signed"),
            item("Year to date", ytd_change(close), "pct_signed"),
            item("1 year", window_change(close, 365), "pct_signed"),
        ]},
        {"title": f"Beta vs {market_label}",
         "note": f"How many percent {ticker} moves for a 1% move of the {short_label(market_label)}, from daily returns.",
         "items": [
            item("2 weeks", b.get(10), "num"),
            item("1 month", b.get(21), "num"),
            item("3 months", b.get(63), "num"),
            item("1 year", b.get(252), "num"),
            item("Ratio, 2 weeks / 3 months", ratio(b.get(10), b.get(63)), "num",
                 hint="Above 1: more market-sensitive lately than its 3-month norm."),
            item("Ratio, 1 month / 3 months", ratio(b.get(21), b.get(63)), "num"),
            item("Yahoo beta (5 years, monthly)", number(info.get("beta")), "num"),
        ]},
        {"title": "Volatility and drawdown", "items": [
            item("Volatility, 1 month (annualized)", volatility(close, 21), "pct"),
            item("Volatility, 3 months (annualized)", volatility(close, 63), "pct"),
            item("Volatility, 1 year (annualized)", volatility(close, 252), "pct"),
            item("Largest drawdown, 1 year", max_dd, "pct_signed"),
            item("From 52-week high", from_high, "pct_signed"),
        ]},
    ]

    corr_items = []
    for symbol, label in compare.items():
        if symbol not in compare_close:
            continue
        rets = aligned_returns(close, compare_close[symbol])
        corr_items.append(item(f"{label}, 3 months", correlation(rets, 63), "num", hint=why.get(symbol)))
        corr_items.append(item(f"{label}, 1 year", correlation(rets, 252), "num"))
    note = "1 = moves together, 0 = unrelated, −1 = opposite."
    if any(s.endswith("-USD") for s in compare_close):
        note += " Crypto trades on weekends too; its returns are matched to US trading days."
    econ.append({"title": "Correlation of daily returns", "note": note, "items": corr_items})

    econ.append({"title": "Volume and trend", "items": [
        item("Last session volume vs 20-day average", vol_vs_avg, "x",
             hint="The doc reads big volume as money entering or leaving."),
        item("Average daily dollar volume, 20 days", dollar_vol, "money_compact"),
        item("Price vs 50-day average", change(last_close, ma50), "pct_signed"),
        item("Price vs 200-day average", change(last_close, ma200), "pct_signed"),
    ]})

    if len(mkt):
        move = float(mkt.iloc[-1, 0])
        market_part = b.get(63) * float(mkt.iloc[-1, 1]) if b.get(63) is not None else None
        session_items = [
            item("Move", move, "pct_signed"),
            item(f"Market part (3-month beta × {market})", market_part, "pct_signed"),
            item("Own part", move - market_part if market_part is not None else None, "pct_signed",
                 hint="What's left after the market's share; a large own part points to company news."),
        ]
        if day is not None and len(day) and day.index[-1].date() == close.index[-1].date():
            moves = session_moves(day)
            session_items += [
                item("First 15 minutes", moves["first15"], "pct_signed"),
                item("First 90 minutes", moves["first90"], "pct_signed"),
                item("Last 30 minutes", moves["last30"], "pct_signed"),
                item("Close vs VWAP", moves["vs_vwap"], "pct_signed"),
            ]
        econ.append({"title": f"Last session ({close.index[-1].strftime('%b %d, %Y')})", "items": session_items})

    # ---- ratios and headline tiles, by kind of asset
    g = lambda key: number(info.get(key))  # noqa: E731
    if kind == "EQUITY":
        ratios = company_ratios(info, current, ticker)
        target = g("targetMeanPrice")
        analysts = g("numberOfAnalystOpinions")
        last_tile = item("Upside to analyst target", change(target, current), "pct_signed",
                         note=f"{int(analysts)} analysts" if analysts else None)
        size_tile = item("Market cap", g("marketCap"), "money_compact")
    elif kind in ("ETF", "MUTUALFUND"):
        ratios = fund_ratios(info)
        expense = g("netExpenseRatio")
        last_tile = item("Expense ratio", expense / 100 if expense is not None else None, "pct")
        size_tile = item("Total assets", g("totalAssets"), "money_compact")
    else:
        ratios = basic_ratios(info)
        last_tile = item("Volatility, 1 year", volatility(close, 252), "pct")
        size_tile = item("Market cap", g("marketCap"), "money_compact")
    kpis = [
        size_tile,
        item("1-year return", window_change(close, 365), "pct_signed"),
        item(f"Beta vs {short_label(market_label)}, 3 months", b.get(63), "num"),
        item("Volatility, 3 months", volatility(close, 63), "pct"),
        item("From 52-week high", from_high, "pct_signed"),
        last_tile,
    ]

    sector = " · ".join(x for x in (info.get("sector"), info.get("industry")) if x)
    data = {
        "schema": SCHEMA,
        "ticker": ticker,
        "kind": kind,
        "name": cfg.get("name") or info.get("longName") or info.get("shortName") or ticker,
        "exchange": EXCHANGES.get(info.get("exchange"), info.get("exchange")),
        "currency": currency,
        "classification": f"Yahoo: {sector}" if sector else None,
        # The domain is the asset's own setting; Yahoo has only sector and industry, its fallback.
        "domain": cfg.get("domain") or info.get("industry") or info.get("category") or None,
        "note": cfg.get("note"),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"Yahoo Finance via yfinance {yf.__version__} (unofficial; cross-check with SEC filings)",
        "compare": [{"symbol": s, "label": l, "why": why.get(s)} for s, l in compare.items()],
        "quote": quote,
        "kpis": kpis,
        "series": series,
        "ratios": ratios,
        "econometrics": econ,
        "warnings": warnings,
    }
    if kind == "EQUITY" and page_dir is not None:
        actions = analyst_actions(ticker, page_dir / KEPT_TABLE)
        if actions:
            data["analyst_actions"] = actions
    if customize:
        ctx = {"config": cfg, "info": info, "history": hist, "intraday": day, "compare": compare_close}
        data = customize(data, ctx) or data
    return clean(data)


# ------------------------------------------------------------------ output

def write_outputs(data: dict, ui_dir: Path) -> Path:
    data_dir = ui_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ticker = data["ticker"]
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    write_atomic(data_dir / f"{ticker}.json", body)
    target = data_dir / f"{ticker}.js"
    write_atomic(target, "window.INVESTING_DATA = window.INVESTING_DATA || {};\n"
                         f"window.INVESTING_DATA[{json.dumps(ticker)}] = {body};\n")
    write_assets(ui_dir)
    return target


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    if not cfg.get("ticker"):
        raise ValueError(f"{path}: no ticker")
    return cfg


def run_once(cfg: dict, ui_dir: Path, customize: Optional[Customize] = None,
             page_dir: Optional[Path] = None) -> bool:
    ticker = cfg["ticker"]
    try:
        data = build(cfg, customize, page_dir)
    except Exception as exc:  # keep the last good files on any failure
        print(f"{datetime.now():%H:%M:%S} {ticker}: update failed, previous data kept: {exc}", file=sys.stderr)
        return False
    target = write_outputs(data, ui_dir)
    q = data["quote"]
    one_day = data["series"].get("1D", {})
    move = f"{q['change_pct'] * 100:+.2f}%" if q.get("change_pct") is not None else "n/a"
    print(f"{datetime.now():%H:%M:%S} {ticker} {q['price']} ({move}) · "
          f"1Y {len(data['series']['1Y']['points'])} bars · "
          f"1D {len(one_day.get('points', []))} bars ({one_day.get('session', 'n/a')}) · "
          f"{len(data['warnings'])} warnings → {target}")
    actions = data.get("analyst_actions")
    if actions:
        found = sum(1 for r in actions["rows"] if r.get("why"))
        line = (f"  analyst updates, past year: {len(actions['rows'])}; "
                f"changes of rating or target: {actions['changes']}, {found} with a reason")
        if actions["pending"]:
            line += f"; {actions['pending']} not looked into yet (the rating_change_cause_searcher skill does that)"
        print(line)
    for w in data["warnings"]:
        print(f"  warning: {w}")
    return True


def main(config_path, customize: Optional[Customize] = None) -> int:
    """Command line for an asset's update script: one update, or one every N minutes."""
    # Windows pipes and log files default to a narrow code page; never crash on a symbol.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    config_path = Path(config_path).resolve()
    cfg = load_config(config_path)
    ui_dir = Path(__file__).resolve().parents[1]  # this engine lives in UI/pipeline/
    parser = argparse.ArgumentParser(description=f"Refresh the {cfg['ticker']} page of the investing UI.")
    parser.add_argument("--every", type=float, metavar="MINUTES",
                        help="keep running and update every MINUTES minutes")
    parser.add_argument("--ticker", help=argparse.SUPPRESS)  # accepted for older callers; must match the config
    args = parser.parse_args()
    if args.ticker and args.ticker.upper() != cfg["ticker"]:
        parser.error(f"this script updates {cfg['ticker']}, not {args.ticker.upper()}")
    if not args.every:
        return 0 if run_once(cfg, ui_dir, customize, config_path.parent) else 1
    print(f"Updating {cfg['ticker']} every {args.every:g} minutes. Press Ctrl+C to stop.")
    try:
        while True:
            run_once(cfg, ui_dir, customize, config_path.parent)
            time.sleep(args.every * 60)
    except KeyboardInterrupt:
        return 0
