r"""Keeps each stock's analyst table and the reasons behind its changes.

A stock's folder UI/asset/<slug>_page/ keeps analyst_table.json: the analyst updates
of the past year as of the last search for reasons, with the firm's reason for each
change. A change is a new rating (upgrade, downgrade, new coverage) or a new price
target; a plain reiteration needs no reason.

    .venv\Scripts\python.exe UI\pipeline\rating_causes.py diff               # every asset in Your assets
    .venv\Scripts\python.exe UI\pipeline\rating_causes.py diff IREN OKTA     # some of them
    .venv\Scripts\python.exe UI\pipeline\rating_causes.py save IREN UI\data\_causes\IREN.found.json

diff compares Yahoo's table now with the kept one. New rows that need no reason go
into the kept table at once. New changes go to UI/data/_causes/<TICKER>.pending.json
for the rating_change_cause_searcher skill, grouped by date (several firms moving
within days usually follow one event), each with the headlines Google News has about
it (free; a head start for the search). The summary's "to_explain" counts them. The
UI server runs diff after each Refresh and starts the skill when that count is above
zero, so the skill only ever works on the new changes.

save reads one or more JSON lists of {"id", "cause", "basis", "source", "url"}. basis
is "reported" when an article gives the firm's reason, or "inferred" when the timing
ties the change to an event, such as results that week; "cause": null records that
nothing was found. Every entry is checked, and nothing is written if one is wrong.
It adds them to the kept table, then runs the asset's update so the page shows them.

Only the past year is kept: older rows drop out of the table.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR.parent))

from pipeline import asset_page as ap  # noqa: E402

UI_DIR = PIPELINE_DIR.parent
WORK_DIR = UI_DIR / "data" / "_causes"   # the skill's working files: what's pending, what it found
FACTS = ("date", "firm", "action", "rating", "previous", "prior_target", "target", "rating_changed", "target_changed")
ABOUT = ("The analyst updates of the past year, as of the last search for reasons, with the firm's reason "
         "for each change of rating or price target. Refresh compares Yahoo's table with this one and sends "
         "only new changes to the rating_change_cause_searcher skill.")
BASES = ("reported", "inferred")
MAX_CAUSE = 160      # characters: the page's Why column holds a line or two
RECHECK_DAYS = 4     # nothing found within this many days of a change: look again next time
GROUP_GAP_DAYS = 2   # changes this close in date go in one group...
GROUP_SPAN_DAYS = 6  # ...that spans at most this many days
NEWS_UA = "Mozilla/5.0 (personal investing research)"
NEWS_PAUSE = 1.0     # seconds between Google News searches
NEWS_BACKOFF = (45, 90)  # seconds to wait before retrying when Google throttles; then stop for this run
FIRM_SKIP = {"co", "inc", "llc", "ltd", "lp", "the", "and", "securities", "capital", "markets", "partners",
             "group", "research", "financial", "company", "corp", "corporation"}
FIRM_ALIASES = {"jp morgan": {"jpmorgan"}, "bank of america": {"bofa"}, "goldman sachs": {"goldman"}}


# -------------------------------------------------------------- the news

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace(".", "").replace("&", " "))).strip()


def firm_patterns(firm: str) -> set:
    """Ways a headline names a research firm: 'HC Wainwright & Co.' -> {'hc wainwright'}."""
    words = [w for w in _norm(firm).split() if w not in FIRM_SKIP]
    full = " ".join(words)
    patterns = {full} if full else set()
    if words and len(words[0]) >= 4 and words[0] != "morgan":  # 'Morgan' alone is ambiguous
        patterns.add(words[0])
    return patterns | FIRM_ALIASES.get(full, set())


def company_word(name: str) -> Optional[str]:
    """The word headlines use for the company: 'IREN Limited' -> 'iren'. None when too short to trust."""
    first = _norm((name or "").split(" ")[0])
    return first if len(first) >= 4 else None


def google_news(query: str) -> list:
    """Google News search results as {title, source, url, published}. Raises on HTTP errors."""
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    request = urllib.request.Request(url, headers={"User-Agent": NEWS_UA})
    with urllib.request.urlopen(request, timeout=15) as response:
        root = ET.fromstring(response.read())
    items = []
    for it in root.findall("./channel/item"):
        title, source = (it.findtext("title") or "").strip(), (it.findtext("source") or "").strip()
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        try:
            published = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            published = None
        items.append({"title": title, "source": source, "url": it.findtext("link"), "published": published})
    return items


def headlines(ticker: str, company: Optional[str], firm: str, when: date) -> list:
    """Up to 5 headlines that name the firm and the company within days of a change, closest in date first."""
    patterns = firm_patterns(firm)
    if not patterns:
        return []
    query = (f'"{max(patterns, key=len)}" {ticker} '
             f"after:{when - timedelta(days=2):%Y-%m-%d} before:{when + timedelta(days=3):%Y-%m-%d}")
    found = []
    for item in google_news(query):
        text = _norm(item["title"])
        if not any(re.search(rf"\b{re.escape(p)}\b", text) for p in patterns):
            continue
        names = [n for n in (_norm(ticker), company) if n]
        if not any(re.search(rf"\b{re.escape(n)}\b", text) for n in names):
            continue
        day = item["published"].date() if item["published"] else None
        found.append((abs((day - when).days) if day else 99, {
            "title": item["title"], "source": item["source"], "url": item["url"],
            "published": day.isoformat() if day else None}))
    found.sort(key=lambda pair: pair[0])
    return [h for _, h in found[:5]]


# -------------------------------------------------------------- the files

def rel(path: Path) -> str:
    return path.resolve().relative_to(UI_DIR.parent).as_posix()


def asset_entry(ticker: str) -> Optional[dict]:
    return next((e for e in ap.load_registry(UI_DIR) if e["ticker"] == ticker), None)


def asset_folder(ticker: str) -> Path:
    """The asset's folder: where Your assets says its pipeline is, or where new_page.py puts it."""
    entry = asset_entry(ticker)
    if entry and entry.get("pipeline"):
        return (UI_DIR / entry["pipeline"]).parent
    return UI_DIR / "asset" / f"{ap.slug(ticker)}_page"


def read_kept(path: Path, ticker: str) -> dict:
    """The kept analyst table: {"ticker", "about", "updated", "rows": {id: row}}."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    rows = doc.get("rows") if isinstance(doc.get("rows"), dict) else {}
    return {"ticker": ticker, "about": ABOUT, "updated": doc.get("updated"), "rows": rows}


def write_kept(path: Path, doc: dict, today: date) -> None:
    doc["rows"] = dict(sorted(doc["rows"].items(), reverse=True))  # newest first
    doc["updated"] = today.isoformat()
    ap.write_atomic(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def facts(row: dict) -> dict:
    return {k: row.get(k) for k in FACTS}


def settle(doc: dict, rows: list, year_ago: str) -> tuple:
    """Put new rows that need no reason into the kept table, and drop rows older than a
    year. Returns (added, dropped). New changes wait for the skill: save adds them."""
    added = 0
    for row in rows:
        if row["id"] not in doc["rows"] and not ap.needs_reason(row):
            doc["rows"][row["id"]] = facts(row)
            added += 1
    old = [i for i, r in doc["rows"].items() if (r.get("date") or i[:10]) < year_ago]
    for i in old:
        del doc["rows"][i]
    return added, len(old)


def waiting(entry: Optional[dict], row: dict, today: date) -> bool:
    """A change still waiting for its reason: new, or recent with nothing found yet
    (its news can come a few days later)."""
    if not ap.needs_reason(row):
        return False
    if not entry or not entry.get("searched"):
        return True
    if entry.get("cause"):
        return False
    try:
        searched = date.fromisoformat(entry["searched"])
        gap = (searched - date.fromisoformat(row["date"])).days
    except ValueError:
        return True
    return gap < RECHECK_DAYS and searched != today


def earlier_headlines(pending_file: Path) -> dict:
    """Headlines a previous diff already found, by change id, so a rerun only fetches the rest."""
    try:
        groups = json.loads(pending_file.read_text(encoding="utf-8-sig")).get("groups") or []
    except (OSError, ValueError, AttributeError):
        return {}
    return {c["id"]: c["headlines"] for g in groups for c in g.get("changes") or []
            if c.get("id") and c.get("headlines") is not None}


def group_by_date(changes: list) -> list:
    """Changes (newest first) in groups of changes days apart: several firms moving
    within days of each other usually follow one event."""
    groups = []
    for row in changes:
        day = date.fromisoformat(row["date"])
        if groups:
            last, first = (date.fromisoformat(groups[-1][i]["date"]) for i in (-1, 0))
            if (last - day).days <= GROUP_GAP_DAYS and (first - day).days <= GROUP_SPAN_DAYS:
                groups[-1].append(row)
                continue
        groups.append([row])
    return [{"from": g[-1]["date"], "to": g[0]["date"], "size": len(g), "changes": g} for g in groups]


def check_entry(e: dict) -> tuple:
    """(problem, clean entry) for one found reason; problem is None when the entry is fine."""
    cause = e.get("cause")
    if cause is None:
        return None, {"cause": None, "basis": None, "source": None, "url": None}
    if not isinstance(cause, str) or not cause.strip():
        return "cause must be text, or null when nothing was found", None
    cause = " ".join(cause.split())
    if len(cause) > MAX_CAUSE:
        return f"cause has {len(cause)} characters; keep it under {MAX_CAUSE}", None
    basis = e.get("basis")
    if basis not in BASES:
        return f"basis must be {' or '.join(BASES)}", None
    source, url = e.get("source"), e.get("url")
    if source is not None and not isinstance(source, str):
        return "source must be text", None
    if url is not None and not (isinstance(url, str) and re.match(r"https?://\S+$", url)):
        return "url must be a web address starting with http:// or https://", None
    source = (source or "").strip() or None
    if basis == "reported" and not (source or url):
        return "a reported cause needs its source or url", None
    return None, {"cause": cause, "basis": basis, "source": source, "url": url or None}


def run_update(ticker: str, folder: Path) -> tuple:
    """Run the asset's update script; (ok, the last lines of its output)."""
    entry = asset_entry(ticker) or {}
    script = UI_DIR / entry["pipeline"] if entry.get("pipeline") else next(iter(sorted(folder.glob("update_*_page.py"))), None)
    if not script or not script.is_file():
        return False, [f"no update script in {rel(folder)}"]
    proc = subprocess.run([sys.executable, str(script)], cwd=str(UI_DIR.parent), capture_output=True,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=300)
    output = (proc.stdout + proc.stderr).decode("utf-8", "replace").strip().splitlines()
    return proc.returncode == 0, output[-4:]


def fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}, indent=1, ensure_ascii=False))
    return 1


# ------------------------------------------------------------ commands

def cmd_diff(args) -> int:
    registry = {e["ticker"]: e for e in ap.load_registry(UI_DIR)}
    tickers = [t.upper() for t in args.tickers] or list(registry)
    today = date.today()
    year_ago = (today - timedelta(days=365)).isoformat()
    report, blocked = [], False
    for ticker in tickers:
        folder = asset_folder(ticker)
        out = WORK_DIR / f"{ticker}.pending.json"
        if not (folder / "config.json").is_file():
            report.append({"ticker": ticker, "error": "not in Your assets"})
            continue
        table = ap.rating_changes(ticker)
        if not table or not table["rows"]:
            report.append({"ticker": ticker, "rows": 0, "to_explain": 0,
                           "note": "Yahoo lists no analyst updates (normal for ETFs and funds)"})
            continue
        path = folder / ap.KEPT_TABLE
        doc = read_kept(path, ticker)
        added, dropped = settle(doc, table["rows"], year_ago)
        if added or dropped or not path.exists():
            write_kept(path, doc, today)
        todo = [r for r in table["rows"] if waiting(doc["rows"].get(r["id"]), r, today)]
        groups = group_by_date(todo)
        if args.limit:  # whole groups, newest first, until the limit is reached
            kept, count = [], 0
            for g in groups:
                if kept and count + g["size"] > args.limit:
                    break
                kept.append(g)
                count += g["size"]
            groups = kept
        listed = [row for g in groups for row in g["changes"]]
        company = company_word((registry.get(ticker) or {}).get("name") or "")
        fetched = earlier_headlines(out)
        for row in listed:
            row["headlines"] = fetched.get(row["id"])
            if row["headlines"] is not None or args.no_news or blocked:
                continue
            for wait in (*NEWS_BACKOFF, None):
                try:
                    row["headlines"] = headlines(ticker, company, row["firm"], date.fromisoformat(row["date"]))
                except urllib.error.HTTPError as exc:
                    if exc.code in (429, 503) and wait:  # Google is throttling: wait, then try again
                        time.sleep(wait)
                        continue
                    blocked = exc.code in (429, 503)  # still throttled: no more news searches this run
                except Exception:
                    pass  # a network hiccup: this change goes without headlines
                break
            time.sleep(NEWS_PAUSE)
        rows = table["rows"]
        summary = {
            "ticker": ticker,
            "rows": len(rows),
            "changes": sum(1 for r in rows if ap.needs_reason(r)),
            "with_reason": sum(1 for r in rows if ap.needs_reason(r)
                               and (doc["rows"].get(r["id"]) or {}).get("cause")),
            "to_explain": len(todo),
        }
        if listed:
            WORK_DIR.mkdir(parents=True, exist_ok=True)
            ap.write_atomic(out, json.dumps({
                "ticker": ticker,
                "company": (registry.get(ticker) or {}).get("name"),
                "today": today.isoformat(),
                "save_to": f"UI/data/_causes/{ticker}.found.json",
                "groups": groups,
            }, indent=1, ensure_ascii=False) + "\n")
            summary.update(listed=len(listed), groups=[f"{g['from']}..{g['to']}: {g['size']}" for g in groups],
                           file=rel(out))
        elif out.exists():
            out.unlink()
        report.append(summary)
    result = {"assets": report}
    if blocked:
        result["news"] = "Google News stopped answering partway; changes with null headlines need a web search."
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


def cmd_save(args) -> int:
    ticker = args.ticker.upper()
    folder = asset_folder(ticker)
    if not (folder / "config.json").is_file():
        return fail(f"{ticker} isn't in Your assets")
    files = [Path(f) for pattern in args.files for f in (sorted(glob.glob(pattern)) or [pattern])]
    entries = []
    for f in files:
        try:
            found = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return fail(f"can't read {f}: {exc}")
        if not isinstance(found, list):
            return fail(f"{f} must hold a JSON list of {{id, cause, basis, source, url}}")
        entries += found
    path = folder / ap.KEPT_TABLE
    doc = read_kept(path, ticker)
    # Only the past year is kept. Rows a little older are still recognized, so a change
    # that aged out while the skill was searching is skipped instead of failing the save.
    table = (ap.rating_changes(ticker, days=400) or {}).get("rows", [])
    known = {r["id"]: r for r in table}
    today = date.today()
    year_ago = (today - timedelta(days=365)).isoformat()
    errors, merged, aged_out, unchanged = [], {}, [], []
    for n, e in enumerate(entries, 1):
        cid = e.get("id") if isinstance(e, dict) else None
        row = (known.get(cid) or doc["rows"].get(cid)) if isinstance(cid, str) else None
        if not row:
            errors.append(f"entry {n}: {cid!r} isn't one of {ticker}'s analyst updates" if cid else f"entry {n}: no id")
            continue
        if (row.get("date") or "") < year_ago:
            aged_out.append(cid)
            continue
        if not ap.needs_reason(row):  # neither the rating nor the target changed
            unchanged.append(cid)
            continue
        problem, entry = check_entry(e)
        if problem:
            errors.append(f"entry {n} ({cid}): {problem}")
            continue
        merged[cid] = dict(facts(row), **entry, searched=today.isoformat())
    if errors:
        print(json.dumps({"ok": False, "saved": 0, "errors": errors}, indent=1, ensure_ascii=False))
        return 1
    doc["rows"].update(merged)
    in_year = [r for r in table if r["date"] >= year_ago]
    settle(doc, in_year, year_ago)
    write_kept(path, doc, today)

    for f in files:  # the skill's working files are done with
        if f.resolve().parent == WORK_DIR.resolve() and f.exists():
            f.unlink()
    pending_file = WORK_DIR / f"{ticker}.pending.json"
    try:
        groups = json.loads(pending_file.read_text(encoding="utf-8-sig")).get("groups") or []
        if all((doc["rows"].get(c.get("id")) or {}).get("searched") for g in groups for c in g.get("changes") or []):
            pending_file.unlink()
    except (OSError, ValueError, AttributeError):
        pass

    kept = [doc["rows"].get(r["id"]) or {} for r in in_year if ap.needs_reason(r)]
    summary = {
        "ok": True,
        "ticker": ticker,
        "file": rel(path),
        "saved": len(merged),
        **({"skipped_older_than_a_year": len(aged_out)} if aged_out else {}),
        **({"skipped_nothing_changed": len(unchanged)} if unchanged else {}),
        "past_year": {
            "rows": len(in_year),
            "changes": len(kept),
            "with_reason": sum(1 for k in kept if k.get("cause")),
            "nothing_found": sum(1 for k in kept if k.get("searched") and not k.get("cause")),
            "not_looked_into": sum(1 for k in kept if not k.get("searched")),
        },
    }
    if not args.no_update:
        ok, lines = run_update(ticker, folder)
        summary.update(page_updated=ok, update_output=lines)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0 if summary.get("page_updated", True) else 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(
        description="The kept analyst tables and the reasons behind their changes (rating_change_cause_searcher).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("diff", "pending"):  # "pending" is the older name
        p = sub.add_parser(name, help="compare Yahoo's table with the kept one; list new changes, with headlines"
                           if name == "diff" else argparse.SUPPRESS)
        p.add_argument("tickers", nargs="*", help="default: every asset in Your assets")
        p.add_argument("--limit", type=int, metavar="N", help="list at most about N changes per asset, newest first")
        p.add_argument("--no-news", action="store_true", help="skip the Google News headlines")
        p.set_defaults(func=cmd_diff)
    p = sub.add_parser("save", help="add found reasons to an asset's kept table, then update its page")
    p.add_argument("ticker")
    p.add_argument("files", nargs="+", help="JSON files, each a list of {id, cause, basis, source, url}")
    p.add_argument("--no-update", action="store_true", help="don't run the asset's update afterwards")
    p.set_defaults(func=cmd_save)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
