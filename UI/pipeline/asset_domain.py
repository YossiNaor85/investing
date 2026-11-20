r"""An asset's domain: its business theme on My watchlist (Data centers, Cybersecurity, ...).

Yahoo has only sector and industry, and they lag behind pivots: it still files IREN, an AI
data center company, under Capital Markets. So the domain is chosen once, by Claude, from
the company's own description, and kept as "domain" in the asset's config.json. The page's
update only reads it. The UI server does this in the background after an asset is added.

    .venv\Scripts\python.exe UI\pipeline\asset_domain.py prompt CIFR              # the question for Claude
    .venv\Scripts\python.exe UI\pipeline\asset_domain.py set CIFR "Data centers"  # save it, update the page

prompt prints the question: the company's description from Yahoo, its sector and industry,
the rules for choosing, and the domains My watchlist already uses (so similar assets
share one). set checks the answer, saves it and runs the asset's update.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR.parent))

from pipeline import asset_page as ap  # noqa: E402

UI_DIR = PIPELINE_DIR.parent
DOMAIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/'().,+-]{0,39}$")
QUESTION = """Name the domain of {ticker} for an investor's watchlist: its business theme in one to three words, the way investors talk about it (for example Data centers, Cybersecurity, Semiconductors, Social media, Quantum computing, Drones, Bitcoin mining).

How to choose:
- Decide from the company's own description below. Yahoo's sector and industry lag behind pivots, so they are only a hint.
- Pick the business that drives the company now, what it leads with and where it is heading, not a legacy line.
- {reuse}
- Don't use any tools or look anything up: the description is enough.

Answer with the domain only, nothing else.

Ticker: {ticker}
Company: {name}
Yahoo's sector and industry: {yahoo}
Description: {business}
"""


def folder_of(entry: dict) -> Path:
    return (UI_DIR / entry["pipeline"]).parent


def config_path(ticker: str) -> Path:
    entry = next((e for e in ap.load_registry(UI_DIR) if e["ticker"] == ticker), None)
    folder = folder_of(entry) if entry and entry.get("pipeline") else UI_DIR / "asset" / f"{ap.slug(ticker)}_page"
    return folder / "config.json"


def watchlist_domains(skip: str) -> list:
    """The domains My watchlist already uses, besides this asset's."""
    found = set()
    for entry in ap.load_registry(UI_DIR):
        if entry["ticker"] == skip or not entry.get("pipeline"):
            continue
        try:
            domain = json.loads((folder_of(entry) / "config.json").read_text(encoding="utf-8-sig")).get("domain")
        except (OSError, ValueError):
            continue
        if domain:
            found.add(domain)
    return sorted(found)


def clean(answer: str) -> str:
    """The domain from Claude's answer: its first line, without quotes, markup or a final period."""
    line = next((l for l in (answer or "").splitlines() if l.strip()), "")
    line = re.sub(r"^(domain\s*:\s*)", "", line.strip(" \t*#`\"'"), flags=re.I).strip(" \t*`\"'.")
    line = " ".join(line.split())
    return line[:1].upper() + line[1:]


def cmd_prompt(args) -> int:
    ticker = args.ticker.upper()
    info = ap.fetch_info(ticker)
    if not info:
        print(f"Yahoo has no data for {ticker}", file=sys.stderr)
        return 1
    others = watchlist_domains(ticker)
    reuse = ("Reuse one of the domains already on the watchlist when it fits: " + ", ".join(others) + "."
             if others else "The watchlist has no domains yet.")
    yahoo = " / ".join(x for x in (info.get("sector"), info.get("industry")) if x) or info.get("category") or "none"
    print(QUESTION.format(ticker=ticker, name=info.get("longName") or info.get("shortName") or ticker, yahoo=yahoo,
                          reuse=reuse, business=(info.get("longBusinessSummary") or "none given")[:2500]))
    return 0


def cmd_set(args) -> int:
    ticker = args.ticker.upper()
    path = config_path(ticker)
    domain = clean(args.domain)
    if not DOMAIN_RE.match(domain) or len(domain.split()) > 5:
        print(json.dumps({"ok": False, "error": f"{domain!r} doesn't look like a domain (one to three words)"}))
        return 1
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"no config for {ticker}: {exc}"}))
        return 1
    out = {}
    for key, value in cfg.items():  # keep the key order, with the domain after the note
        if key != "domain":
            out[key] = value
        if key == "note":
            out["domain"] = domain
    out.setdefault("domain", domain)
    ap.write_atomic(path, json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    result = {"ok": True, "ticker": ticker, "domain": domain}
    if not args.no_update:
        script = next(iter(sorted(path.parent.glob("update_*_page.py"))), None)
        proc = subprocess.run([sys.executable, str(script)], cwd=str(UI_DIR.parent), capture_output=True, timeout=300)
        result["page_updated"] = proc.returncode == 0
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("page_updated", True) else 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="An asset's domain on My watchlist, chosen by Claude from its description.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prompt", help="print the question for Claude: the description, the rules, the watchlist's domains")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_prompt)
    p = sub.add_parser("set", help="save an asset's domain in its config.json, then update its page")
    p.add_argument("ticker")
    p.add_argument("domain")
    p.add_argument("--no-update", action="store_true", help="don't run the asset's update afterwards")
    p.set_defaults(func=cmd_set)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
