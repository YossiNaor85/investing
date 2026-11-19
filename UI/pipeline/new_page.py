r"""Create, check and manage the asset pages of the investing UI.

    .venv\Scripts\python.exe UI\pipeline\new_page.py inspect NVDA
    .venv\Scripts\python.exe UI\pipeline\new_page.py create NVDA --compare "SMH=Semiconductors (SMH)" --why "SMH=AI chip demand"
    .venv\Scripts\python.exe UI\pipeline\new_page.py check NVDA
    .venv\Scripts\python.exe UI\pipeline\new_page.py list
    .venv\Scripts\python.exe UI\pipeline\new_page.py remove NVDA

The asset-page skill (.claude/skills/asset-page/) drives these commands.
--ui-dir points at another copy of the UI folder, for testing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import string
import subprocess
import sys
from datetime import date
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR.parent))

from pipeline import asset_page as ap  # noqa: E402

TEMPLATE = PIPELINE_DIR / "templates" / "update_page.py.tmpl"
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")     # what UI/static/app.js accepts
SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,14}$")  # comparison series may be indexes or futures
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# Starting points for comparison series. They're suggestions: the skill picks
# what actually moves the stock (see references/compare-series.md).
SECTOR_ETF = {
    "Technology": ("XLK", "Technology (XLK)"),
    "Financial Services": ("XLF", "Financials (XLF)"),
    "Healthcare": ("XLV", "Health care (XLV)"),
    "Energy": ("XLE", "Energy (XLE)"),
    "Industrials": ("XLI", "Industrials (XLI)"),
    "Consumer Cyclical": ("XLY", "Consumer discretionary (XLY)"),
    "Consumer Defensive": ("XLP", "Consumer staples (XLP)"),
    "Utilities": ("XLU", "Utilities (XLU)"),
    "Real Estate": ("XLRE", "Real estate (XLRE)"),
    "Basic Materials": ("XLB", "Materials (XLB)"),
    "Communication Services": ("XLC", "Communication services (XLC)"),
}
INDUSTRY_ETF = [  # (text in Yahoo's industry, symbol, label); the first match wins
    ("Semiconductor", "SMH", "Semiconductors (SMH)"),
    ("Software", "IGV", "Software (IGV)"),
    ("Biotechnology", "XBI", "Biotech (XBI)"),
    ("Drug Manufacturers", "XPH", "Pharmaceuticals (XPH)"),
    ("Medical Devices", "IHI", "Medical devices (IHI)"),
    ("Banks - Regional", "KRE", "Regional banks (KRE)"),
    ("Banks", "KBE", "Banks (KBE)"),
    ("Insurance", "KIE", "Insurance (KIE)"),
    ("Oil & Gas E&P", "XOP", "Oil and gas producers (XOP)"),
    ("Oil & Gas Equipment", "OIH", "Oil services (OIH)"),
    ("Oil & Gas", "XLE", "Energy (XLE)"),
    ("Gold", "GDX", "Gold miners (GDX)"),
    ("Silver", "SIL", "Silver miners (SIL)"),
    ("Copper", "COPX", "Copper miners (COPX)"),
    ("Uranium", "URA", "Uranium (URA)"),
    ("Residential Construction", "ITB", "Homebuilders (ITB)"),
    ("REIT", "VNQ", "Real estate (VNQ)"),
    ("Aerospace & Defense", "ITA", "Aerospace and defense (ITA)"),
    ("Airlines", "JETS", "Airlines (JETS)"),
    ("Utilities", "XLU", "Utilities (XLU)"),
    ("Solar", "TAN", "Solar (TAN)"),
    ("Internet Retail", "IBUY", "Online retail (IBUY)"),
    ("Retail", "XRT", "Retail (XRT)"),
]
DRIVERS = [  # (word in the business summary, symbol, label, reason)
    (r"\bbitcoin\b", "BTC-USD", "Bitcoin (BTC-USD)", "bitcoin is part of the business"),
    (r"\bcrude oil\b|\boil and gas\b", "USO", "Crude oil (USO)", "oil prices drive revenue"),
    (r"\bnatural gas\b", "UNG", "Natural gas (UNG)", "gas prices drive revenue"),
    (r"\bgold\b", "GLD", "Gold (GLD)", "gold prices drive revenue"),
    (r"\bcopper\b", "CPER", "Copper (CPER)", "copper prices drive revenue"),
    (r"\buranium\b", "URA", "Uranium (URA)", "uranium prices drive revenue"),
]


def ui_dir_from(args) -> Path:
    return Path(args.ui_dir).resolve() if args.ui_dir else PIPELINE_DIR.parent


def page_paths(ui: Path, ticker: str) -> tuple:
    s = ap.slug(ticker)
    page_dir = ui / f"{s}_page"
    return page_dir, page_dir / f"update_{s}_page.py", page_dir / "config.json"


def fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}, indent=2))
    return 1


def parse_pairs(pairs) -> dict:
    """["SMH=Semiconductors (SMH)", ...] -> {"SMH": "Semiconductors (SMH)", ...}, in order."""
    out = {}
    for pair in pairs or []:
        symbol, sep, text = pair.partition("=")
        symbol = symbol.strip().upper()
        if not sep or not SYMBOL_RE.match(symbol):
            raise ValueError(f"expected SYMBOL=text, got {pair!r}")
        out[symbol] = text.strip()
    return out


def suggest(info: dict) -> list:
    """Starting points for the comparison series, from Yahoo's classification."""
    out = []
    industry = info.get("industry") or ""
    kind = (info.get("quoteType") or "").upper()
    if kind == "EQUITY":
        for text, symbol, label in INDUSTRY_ETF:
            if text in industry:
                out.append({"symbol": symbol, "label": label, "why": f"its industry ({industry})"})
                break
        sector = SECTOR_ETF.get(info.get("sector") or "")
        if sector and not out:
            out.append({"symbol": sector[0], "label": sector[1], "why": f"its sector ({info.get('sector')})"})
        summary = (info.get("longBusinessSummary") or "").lower()
        for pattern, symbol, label, why in DRIVERS:
            if re.search(pattern, summary) and all(o["symbol"] != symbol for o in out):
                out.append({"symbol": symbol, "label": label, "why": why})
    elif kind in ("ETF", "MUTUALFUND"):
        out.append({"symbol": "QQQ", "label": "Nasdaq 100 (QQQ)", "why": "a second broad market, if the fund is growth-heavy"})
    return out


# ---------------------------------------------------------------- commands

def cmd_inspect(args) -> int:
    ticker = args.ticker.upper()
    if not TICKER_RE.match(ticker):
        return fail(f"{ticker!r} isn't a ticker this UI accepts (letters, digits, '.' and '-', up to 12)")
    ui = ui_dir_from(args)
    info = ap.fetch_info(ticker)
    try:
        days = len(ap.fetch_history(ticker, "1mo", "1d"))
    except RuntimeError:
        days = 0
    kind = (info.get("quoteType") or "").upper() or None
    notes = []
    if not info or not days:
        notes.append("Yahoo has no data for this symbol. Check the spelling, or the exchange suffix (e.g. TEVA.TA).")
    if kind and kind not in ("EQUITY", "ETF", "MUTUALFUND"):
        notes.append(f"This is a {kind.lower()}, not a stock or fund: ask the user before creating a page.")
    if info.get("currency") and info.get("currency") != "USD":
        notes.append(f"Prices are in {info.get('currency')}; consider a local market index instead of SPY.")
    page_dir, _, cfg_path = page_paths(ui, ticker)
    registered = any(a["ticker"] == ticker for a in ap.load_registry(ui))
    print(json.dumps({
        "ok": bool(info) and days > 0,
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName"),
        "type": kind,
        "exchange": ap.EXCHANGES.get(info.get("exchange"), info.get("exchange")),
        "currency": info.get("currency"),
        "country": info.get("country"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "category": info.get("category"),
        "market_cap": info.get("marketCap") or info.get("totalAssets"),
        "trading_days_last_month": days,
        "business": (info.get("longBusinessSummary") or "")[:700],
        "registered": registered,
        "page_exists": cfg_path.exists(),
        "page_dir": str(page_dir),
        "suggested_market": "SPY",
        "suggested_compare": suggest(info),
        "notes": notes,
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_create(args) -> int:
    ticker = args.ticker.upper()
    if not TICKER_RE.match(ticker):
        return fail(f"{ticker!r} isn't a ticker this UI accepts")
    ui = ui_dir_from(args)
    if not (ui / "index.html").exists() or not (ui / "pipeline").is_dir():
        return fail(f"{ui} doesn't look like the UI folder (no index.html or pipeline/)")
    try:
        compare = parse_pairs(args.compare)
        why = parse_pairs(args.why)
    except ValueError as exc:
        return fail(str(exc))
    market = args.market.upper()
    if market not in compare:
        compare = {market: ap.MARKET_LABELS.get(market, market), **compare}

    page_dir, script, cfg_path = page_paths(ui, ticker)
    old = {}
    if cfg_path.exists():
        if not args.rebuild:
            return fail(f"{cfg_path} already exists. Pass --rebuild to rewrite its config "
                        "(the update script, and any customize() code in it, are kept).")
        old = json.loads(cfg_path.read_text(encoding="utf-8"))

    info = ap.fetch_info(ticker)
    if not info:
        return fail(f"Yahoo has no data for {ticker}")
    name = info.get("longName") or info.get("shortName") or ticker
    today = date.today().isoformat()
    cfg = {
        "ticker": ticker,
        "name": name,
        "market": market,
        "compare": compare,
        "why": why,
        "note": args.note if args.note is not None else old.get("note"),
        "created": old.get("created", today),
        "updated": today,
    }
    page_dir.mkdir(parents=True, exist_ok=True)
    ap.write_atomic(cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    script_created = False
    if not script.exists():
        text = string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
            TICKER=ticker, NAME=name, SLUG=ap.slug(ticker), CREATED=today)
        script.write_text(text, encoding="utf-8")
        script_created = True

    entries = ap.load_registry(ui)
    entry = {"ticker": ticker, "name": name, "pipeline": script.relative_to(ui).as_posix(), "added": today}
    for i, e in enumerate(entries):
        if e["ticker"] == ticker:
            entries[i] = dict(e, name=name, pipeline=entry["pipeline"])
            break
    else:
        entries.append(entry)
    ap.save_registry(ui, entries)

    proc = subprocess.run([sys.executable, str(script)], cwd=str(ui.parent), capture_output=True,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=300)
    output = (proc.stdout + proc.stderr).decode("utf-8", "replace").strip().splitlines()
    print(json.dumps({
        "ok": proc.returncode == 0,
        "ticker": ticker,
        "name": name,
        "config": str(cfg_path),
        "script": str(script),
        "script_created": script_created,
        "registered_position": [e["ticker"] for e in entries].index(ticker) + 1,
        "compare": compare,
        "first_update": output[-6:],
        "link": f"http://127.0.0.1:8765/#{ticker}",
    }, indent=2, ensure_ascii=False))
    return 0 if proc.returncode == 0 else 1


def find_edge():
    return next((p for p in EDGE_PATHS if Path(p).exists()), None)


def cmd_check(args) -> int:
    ticker = args.ticker.upper()
    ui = ui_dir_from(args)
    path = ui / "data" / f"{ticker}.json"
    if not path.exists():
        return fail(f"no data file for {ticker}: run its update script first")
    d = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    windows = {w: len((d.get("series", {}).get(w) or {}).get("points", [])) for w in ("1Y", "3M", "1D")}
    if windows["1Y"] < 120:
        problems.append(f"only {windows['1Y']} daily bars in the 1-year window")
    if not windows["1D"]:
        problems.append("no intraday bars for the 1-day window")
    empty = {}
    for section in ("ratios", "econometrics"):
        for g in d.get(section, []):
            missing = [i["label"] for i in g.get("items", []) if i.get("value") in (None, "", [])]
            if missing:
                empty[g["title"]] = missing
    if d.get("schema") != ap.SCHEMA:
        problems.append(f"data schema {d.get('schema')} differs from the engine's {ap.SCHEMA}")

    shots = []
    edge = find_edge()
    if edge and not args.no_screenshots:
        out_dir = ui / "data" / "_checks"
        out_dir.mkdir(parents=True, exist_ok=True)
        for win in ("1Y", "1D"):
            out = out_dir / f"{ticker}-{win}.png"
            url = (ui / "index.html").as_uri() + f"#{ticker}/{win}"
            subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            f"--user-data-dir={out_dir / 'edge-profile'}", "--window-size=1280,1900",
                            "--virtual-time-budget=8000", f"--screenshot={out}", url],
                           capture_output=True, timeout=90)
            if out.exists():
                shots.append(str(out))
    elif not edge:
        problems.append("Microsoft Edge not found, so no screenshots were taken")

    print(json.dumps({
        "ok": not problems,
        "ticker": ticker,
        "kind": d.get("kind"),
        "updated_at": d.get("updated_at"),
        "windows": windows,
        "empty_values": empty,
        "warnings": d.get("warnings", []),
        "problems": problems,
        "screenshots": shots,
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_list(args) -> int:
    print(json.dumps(ap.load_registry(ui_dir_from(args)), indent=2, ensure_ascii=False))
    return 0


def cmd_remove(args) -> int:
    ticker = args.ticker.upper()
    ui = ui_dir_from(args)
    entries = ap.load_registry(ui)
    kept = [e for e in entries if e["ticker"] != ticker]
    if len(kept) == len(entries):
        return fail(f"{ticker} isn't in Your assets")
    ap.save_registry(ui, kept)
    ap.write_assets(ui)
    page_dir, _, _ = page_paths(ui, ticker)
    print(json.dumps({"ok": True, "removed": ticker, "folder_kept": str(page_dir)}, indent=2))
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ui-dir", help="the UI folder to work on (default: the one this script is in)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="look a ticker up and suggest comparison series")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("create", help="create (or with --rebuild, rewrite) an asset's page and pipeline")
    p.add_argument("ticker")
    p.add_argument("--market", default="SPY", help="the series beta is measured against (default SPY)")
    p.add_argument("--compare", action="append", metavar="SYMBOL=LABEL", help="a comparison series; repeat")
    p.add_argument("--why", action="append", metavar="SYMBOL=REASON", help="why a series matters; repeat")
    p.add_argument("--note", help="a line shown under the asset's name, e.g. why it's followed")
    p.add_argument("--rebuild", action="store_true", help="rewrite an existing config")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("check", help="validate an asset's data and screenshot its page")
    p.add_argument("ticker")
    p.add_argument("--no-screenshots", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("list", help="the assets in Your assets, in order")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("remove", help="take an asset out of Your assets (its folder is kept)")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
