r"""Share values from the last quarterly report: what one share would be worth if the market
valued the company by a single fundamental, from the bears' floors (net cash, book value)
to the bulls' growth multiples. A plain calculation, no AI: the asset's update runs it
every time, so every asset added gets it. The share_values skill (.claude/skills/) maintains it.

Each value is one fundamental per share times one multiple. Which side argues for it
(bears, neutral, bulls), the market mood that would take the price there, and why, all come
from one dictionary, bull_bear_dictionary.json next to this file. It's the same for every
asset and written for review by an expert:

    fundamental, per share               bears           neutral                       bulls
    net cash (cash minus all debt)       1x              -                             -
    tangible book value                  1x              -                             -
    book value                           1x              -                             -
    revenue, last four quarters          1x              3x                            -
    revenue pace, the last quarter x 4   -               -                             10x
    earnings, last four quarters         12x             S&P 500's P/E, sector's P/E   35x
    EBITDA, last four quarters           8x - net debt   14x - net debt                25x - net debt
    free cash flow, last four quarters   12x             22x                           40x

Everything per share uses the report's own share count at the quarter's end, so every
figure comes from the same report. The S&P 500's and the sector's P/E are live from Yahoo:
the market series (SPY) and the asset's first comparison series that is an ETF. A
fundamental that is zero or negative over the period (a loss, cash burn) gives no value,
and the result lists it as skipped.

    .venv\Scripts\python.exe UI\pipeline\share_values.py IREN           # print the table
    .venv\Scripts\python.exe UI\pipeline\share_values.py --dictionary   # the dictionary, as a table
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

DICTIONARY = Path(__file__).resolve().with_name("bull_bear_dictionary.json")
SIDES = ("bears", "neutral", "bulls")
LIVE_MULTIPLES = ("market_pe", "sector_pe")
FUNDAMENTALS = {
    "net_cash": "Net cash (cash minus all debt)",
    "tangible_book": "Tangible book value",
    "book": "Book value",
    "revenue": "Revenue, last four quarters",
    "revenue_pace": "Revenue pace (last quarter × 4)",
    "earnings": "Earnings, last four quarters",
    "ebitda": "EBITDA, last four quarters",
    "fcf": "Free cash flow, last four quarters",
}
NAMES = {"net_cash": "net cash", "tangible_book": "tangible book value", "book": "book value", "revenue": "revenue",
         "revenue_pace": "revenue", "earnings": "earnings", "ebitda": "EBITDA", "fcf": "free cash flow"}


def load_dictionary(path: Path = DICTIONARY) -> dict:
    """The bull/bear dictionary, checked: every value names a known fundamental, a side and a multiple."""
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    for v in doc["values"]:
        if v["fundamental"] not in FUNDAMENTALS:
            raise ValueError(f"{path.name}: {v['id']} has an unknown fundamental {v['fundamental']!r}")
        if v["side"] not in SIDES:
            raise ValueError(f"{path.name}: {v['id']} has side {v['side']!r}; use one of {', '.join(SIDES)}")
        if not (v["multiple"] in LIVE_MULTIPLES or (isinstance(v["multiple"], (int, float)) and v["multiple"] > 0)):
            raise ValueError(f"{path.name}: {v['id']} needs a positive multiple or one of {', '.join(LIVE_MULTIPLES)}")
    return doc


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _newest_first(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    return df.reindex(sorted(df.columns, reverse=True), axis=1)


def _at_quarter_end(df: Optional[pd.DataFrame], names: list) -> Optional[float]:
    """A balance sheet line at the newest quarter's end: the first of `names` that's there."""
    if df is None:
        return None
    for name in names:
        if name in df.index:
            v = _num(df.loc[name].iloc[0])
            if v is not None:
                return v
    return None


def _four_quarters(df: Optional[pd.DataFrame], names: list) -> tuple:
    """(sum over the newest four quarters, quarters found) for the first of `names` that's there.
    With fewer than four, the sum is annualized."""
    if df is None:
        return None, 0
    for name in names:
        if name in df.index:
            vals = [v for v in (_num(x) for x in df.loc[name].iloc[:4]) if v is not None]
            if vals:
                return sum(vals) * 4 / len(vals), len(vals)
    return None, 0


def _trailing_pe(symbol: str) -> tuple:
    """(trailing P/E, Yahoo's quoteType) of a series; tried twice, since Yahoo sometimes drops an answer."""
    for attempt in range(2):
        try:
            info = yf.Ticker(symbol).info or {}
            pe = _num(info.get("trailingPE"))
            return (pe if pe and pe > 0 else None), (info.get("quoteType") or "").upper()
        except Exception:
            time.sleep(1.5)
    return None, None


def reference_pe(market: str, compare: dict) -> tuple:
    """(the market's P/E, (the sector's P/E, its label) or None), live from Yahoo: the market
    series and the first comparison series that is an ETF."""
    market_pe, _ = _trailing_pe(market)
    for symbol, label in (compare or {}).items():
        if symbol == market:
            continue
        pe, kind = _trailing_pe(symbol)
        if kind == "ETF" and pe:
            return market_pe, (pe, label)
    return market_pe, None


def report_values(ticker: str, info: dict, price: Optional[float], market: str = "SPY",
                  compare: Optional[dict] = None) -> Optional[dict]:
    """The share values table from the last quarterly report, lowest value first; None when
    Yahoo has no quarterly report for the asset."""
    if not price or price <= 0:
        return None
    tk = yf.Ticker(ticker)
    try:
        bs = _newest_first(tk.quarterly_balance_sheet)
        inc = _newest_first(tk.quarterly_income_stmt)
        cf = _newest_first(tk.quarterly_cashflow)
    except Exception:
        return None
    if bs is None or inc is None:
        return None
    quarter_end = f"{bs.columns[0]:%Y-%m-%d}"
    report_currency, price_currency = info.get("financialCurrency"), info.get("currency")
    if report_currency and price_currency and report_currency != price_currency:
        return {"quarter_end": quarter_end, "rows": [], "skipped": [],
                "notes": [f"The report is in {report_currency} and the price in {price_currency}, so the values aren't comparable."]}

    # The report's own share count, so every figure comes from the same quarter.
    shares = _at_quarter_end(bs, ["Ordinary Shares Number", "Share Issued"]) or _num(info.get("sharesOutstanding"))
    if not shares:
        return None
    equity = _at_quarter_end(bs, ["Stockholders Equity", "Common Stock Equity"])
    tangible = _at_quarter_end(bs, ["Tangible Book Value"])
    if tangible is None and equity is not None:
        tangible = equity - (_at_quarter_end(bs, ["Goodwill"]) or 0) - (_at_quarter_end(bs, ["Other Intangible Assets"]) or 0)
    debt = _at_quarter_end(bs, ["Total Debt"]) or 0.0
    cash = _at_quarter_end(bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"])
    net_cash = cash - debt if cash is not None else None
    revenue, n_revenue = _four_quarters(inc, ["Total Revenue"])
    last_revenue = _num(inc.loc["Total Revenue"].iloc[0]) if "Total Revenue" in inc.index else None
    earnings, n_earn = _four_quarters(inc, ["Net Income Common Stockholders", "Net Income"])
    ebitda, n_ebitda = _four_quarters(inc, ["Normalized EBITDA", "EBITDA"])  # without one-off items
    fcf, n_fcf = _four_quarters(cf, ["Free Cash Flow"])

    def per(v):
        return v / shares if v is not None else None

    per_share = {
        "net_cash": per(net_cash), "tangible_book": per(tangible), "book": per(equity), "revenue": per(revenue),
        "revenue_pace": per(last_revenue * 4) if last_revenue is not None else None,
        "earnings": per(earnings), "ebitda": per(ebitda), "fcf": per(fcf),
    }
    net_debt_ps = -per_share["net_cash"] if per_share["net_cash"] is not None else 0.0
    market_pe, sector = reference_pe(market, compare or {})
    market_label = (compare or {}).get(market, market).split(" (")[0]

    rows, skipped = [], []
    for v in load_dictionary()["values"]:
        fund, multiple, mood = v["fundamental"], v["multiple"], v["sentiment"]
        value_ps = per_share.get(fund)
        if value_ps is None:
            continue
        if fund != "net_cash" and value_ps <= 0:
            if NAMES[fund] not in skipped:
                skipped.append(NAMES[fund])
            continue
        if multiple == "market_pe":
            if not market_pe:
                continue
            multiple, shown = market_pe, f"{market_pe:.1f}× ({market_label})"
        elif multiple == "sector_pe":
            if not sector:
                continue
            multiple, label = sector
            shown = f"{multiple:.1f}× ({label})"
        else:
            shown = f"{multiple:g}×"
        if fund == "ebitda":
            shown += ", less net debt"
        value = value_ps * multiple - (net_debt_ps if fund == "ebitda" else 0.0)
        rows.append({
            "id": v["id"], "fundamental": FUNDAMENTALS[fund], "per_share": round(value_ps, 4),
            "multiple": round(multiple, 2), "multiple_label": shown, "value": round(value, 2),
            "vs_price": round(value / price - 1, 4) if value > 0 else None,
            "side": v["side"], "sentiment": mood, "why": v["why"],
        })
    rows.sort(key=lambda r: r["value"])

    notes = []
    short = [n for n, q in (("revenue", n_revenue), ("earnings", n_earn), ("EBITDA", n_ebitda), ("free cash flow", n_fcf))
             if 0 < q < 4]
    if short:
        notes.append("Annualized from fewer than four quarters, all Yahoo has: " + ", ".join(short) + ".")
    return {"quarter_end": quarter_end, "shares": shares, "price": price, "rows": rows,
            "skipped": skipped, "notes": notes}


def dictionary_table() -> str:
    """The dictionary as a Markdown table, for the expert's review."""
    doc = load_dictionary()
    out = ["| Value | Fundamental | Multiple | Side | Market mood | Why this side |", "|---|---|---|---|---|---|"]
    for v in doc["values"]:
        m = v["multiple"]
        live = {"market_pe": "S&P 500's P/E (live)", "sector_pe": "sector ETF's P/E (live)"}
        shown = live[m] if m in live else f"{m:g}×"
        out.append(f"| {v['id']} | {FUNDAMENTALS[v['fundamental']]} | {shown} | {v['side']} | {v['sentiment']} | {v['why']} |")
    return "\n".join(out)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="Share values from an asset's last quarterly report.")
    parser.add_argument("ticker", nargs="?")
    parser.add_argument("--dictionary", action="store_true", help="print the bull/bear dictionary as a table")
    args = parser.parse_args()
    if args.dictionary:
        print(dictionary_table())
        return 0
    if not args.ticker:
        parser.error("give a ticker, or --dictionary")
    ui_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ui_dir))
    from pipeline import asset_page as ap  # here: asset_page imports this module too

    ticker = args.ticker.upper()
    entry = next((e for e in ap.load_registry(ui_dir) if e["ticker"] == ticker), None)
    cfg = {}
    if entry and entry.get("pipeline"):
        cfg = json.loads(((ui_dir / entry["pipeline"]).parent / "config.json").read_text(encoding="utf-8-sig"))
    info = ap.fetch_info(ticker)
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    market = cfg.get("market", "SPY")
    compare = dict(cfg.get("compare") or {})
    compare.setdefault(market, ap.MARKET_LABELS.get(market, market))
    result = report_values(ticker, info, price, market, compare)
    if not result:
        print(f"No quarterly report from Yahoo for {ticker}.")
        return 1
    print(f"{ticker}: quarter ended {result['quarter_end']}, price {price}, shares {result['shares'] / 1e6:,.1f}M")
    for r in result["rows"]:
        vs = f"{r['vs_price'] * 100:+.0f}%" if r["vs_price"] is not None else "-"
        print(f"  {r['value']:>10,.2f}  {vs:>6}  {r['side']:<7}  {r['fundamental']} ({r['per_share']:,.2f}/share) × {r['multiple_label']}")
    for s in result["skipped"]:
        print(f"  skipped: {s} (zero or negative)")
    for n in result["notes"]:
        print("  note:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
