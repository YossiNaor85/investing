r"""Serve the investing UI on this computer, and run its scripts on demand.

    .venv\Scripts\python.exe UI\server.py           # http://127.0.0.1:8765/
    .venv\Scripts\python.exe UI\server.py --open    # ...and open it in the browser

Every button runs a plain Python script here:

    POST   /api/refresh?ticker=IREN  run the asset's pipeline (listed in UI/assets.json)
    POST   /api/assets?ticker=RIOT   add an asset with UI/pipeline/new_page.py: restore it if it
                                     was deleted before, otherwise create it (create --auto)
    DELETE /api/assets?ticker=RIOT   delete it (new_page.py delete): off the list, folder archived
                                     to UI/asset/_deleted/, data files removed
    GET    /api/status?ticker=RIOT[&job=add|causes]   progress of a refresh, an add or a reason search

Two things use AI, in the background, and only for what's new:
- After an add, Claude names the asset's domain once from the company's own description
  (UI/pipeline/asset_domain.py), with no tools at all.
- After a refresh or an add, the server compares the asset's analyst table with the one
  kept in its folder (UI/pipeline/rating_causes.py diff, a plain script). Only when there
  are new changes of rating or price target does Claude Code run the
  rating_change_cause_searcher skill on just those changes, allowed only web research
  and the skill's own script and working folder.
AUTO_AI below turns both off.

The server listens on 127.0.0.1 only, so no other computer can reach it.
It serves only the page, its static files, data/ and my_thoughts.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

UI_DIR = Path(__file__).resolve().parent
REPO_DIR = UI_DIR.parent
NEW_PAGE = UI_DIR / "pipeline" / "new_page.py"
CAUSES = UI_DIR / "pipeline" / "rating_causes.py"
DOMAIN = UI_DIR / "pipeline" / "asset_domain.py"
WORK_DIR = UI_DIR / "data" / "_causes"
TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")
REFRESH_TIMEOUT_S = 300
ADD_TIMEOUT_S = 300
SERVED = ("/", "/index.html", "/my_thoughts.md")  # exact paths; also everything under:
SERVED_DIRS = ("/static/", "/data/")

# The background AI: a new asset's domain, and the reasons behind new analyst changes.
AUTO_AI = True                  # False: the buttons never start Claude; run the skills by hand instead
DOMAIN_TIMEOUT_S = 300
DOMAIN_BUDGET_USD = 0.5
DIFF_TIMEOUT_S = 900            # the diff also fetches free news headlines for each new change
REASONS_TIMEOUT_S = 3600        # a first search for a newly added stock can take a while
BUDGET_PER_CHANGE_USD = 0.5     # spending cap for one search: this much per change...
BUDGET_MIN_USD, BUDGET_MAX_USD = 2.0, 30.0  # ...within these bounds
REASON_TOOLS = [                # all the background run may use; anything else is refused
    "Skill", "Read", "Glob", "Grep", "WebSearch", "WebFetch", "Agent",
    "Write(UI/data/_causes/**)", "Edit(UI/data/_causes/**)",
    "Bash(.venv/Scripts/python.exe UI/pipeline/rating_causes.py *)",
    "PowerShell(.venv/Scripts/python.exe UI/pipeline/rating_causes.py *)",
    "PowerShell(.\\.venv\\Scripts\\python.exe UI\\pipeline\\rating_causes.py *)",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(ticker: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", ticker.lower()).strip("_")


def pipeline_for(ticker: str) -> Optional[Path]:
    """The asset's update script from UI/assets.json, or None if it isn't followed."""
    try:
        assets = json.loads((UI_DIR / "assets.json").read_text(encoding="utf-8-sig")).get("assets", [])
    except (OSError, ValueError):
        return None
    for a in assets:
        if a.get("ticker") == ticker and a.get("pipeline"):
            script = (UI_DIR / a["pipeline"]).resolve()
            if script.is_file() and UI_DIR in script.parents:
                return script
    return None


def archived(ticker: str) -> bool:
    """True if a deleted copy of this asset's page is waiting in UI/asset/_deleted/."""
    return any((UI_DIR / "asset" / "_deleted").glob(f"{slug(ticker)}_page-*"))


def run(cmd: list, timeout: int) -> tuple:
    """(exit code, stdout, stderr) of a command run from the repo root."""
    proc = subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, timeout=timeout,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def claude_cli() -> Optional[str]:
    """Claude Code's command line; on Windows the native claude.exe, not the npm .cmd shim."""
    return shutil.which("claude.exe") or shutil.which("claude")


def diff(ticker: str, news: bool = True) -> dict:
    """The asset's analyst table compared with the kept one: rating_causes.py diff's summary."""
    cmd = [sys.executable, str(CAUSES), "diff", ticker] + ([] if news else ["--no-news"])
    code, out, err = run(cmd, DIFF_TIMEOUT_S)
    try:
        return json.loads(out)["assets"][0]
    except (ValueError, KeyError, IndexError):
        raise RuntimeError((err or out).strip()[-300:] or f"exit code {code}")


def log_run(ticker: str, kind: str, code: int, result: dict, **extra) -> None:
    """One line per background Claude run, with its cost, in UI/data/_causes/<TICKER>.log."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    with (WORK_DIR / f"{ticker}.log").open("a", encoding="utf-8") as log:
        log.write(json.dumps(dict({"at": now(), "kind": kind, "exit": code, "cost_usd": result.get("total_cost_usd"),
                                   "turns": result.get("num_turns")}, **extra, result=result.get("result")),
                             ensure_ascii=False) + "\n")


def claude_json(cmd: list, timeout: int) -> tuple:
    """(exit code, result) of a non-interactive Claude run with --output-format json."""
    code, out, err = run(cmd, timeout)
    try:
        return code, json.loads(out)
    except ValueError:
        return code, {"is_error": True, "result": (err or out).strip()[-500:]}


def config_domain(ticker: str) -> Optional[str]:
    script = pipeline_for(ticker)
    try:
        return json.loads((script.parent / "config.json").read_text(encoding="utf-8-sig")).get("domain") if script else None
    except (OSError, ValueError):
        return None


def name_domain(ticker: str) -> Optional[str]:
    """Have Claude name a new asset's domain from the company's own description, once, and
    save it in the asset's config.json. No tools: the question carries the description."""
    cli = claude_cli()
    if not cli or config_domain(ticker):
        return None
    JOBS.note(f"causes:{ticker}", phase="domain")
    code, prompt, _ = run([sys.executable, str(DOMAIN), "prompt", ticker], 120)
    if code != 0 or not prompt.strip():
        return None
    code, result = claude_json([cli, "-p", prompt, "--permission-mode", "dontAsk", "--output-format", "json",
                                "--max-budget-usd", f"{DOMAIN_BUDGET_USD:.2f}", "--no-session-persistence"],
                               DOMAIN_TIMEOUT_S)
    answer = (result.get("result") or "").strip()
    saved = None
    if code == 0 and not result.get("is_error") and answer:
        set_code, out, _ = run([sys.executable, str(DOMAIN), "set", ticker, answer], DOMAIN_TIMEOUT_S)
        try:
            saved = json.loads(out).get("domain") if set_code == 0 else None
        except ValueError:
            saved = None
    log_run(ticker, "domain", code, result, domain=saved)
    return saved


def reasons_job(ticker: str, new_asset: bool = False) -> Callable[[], dict]:
    """For a new asset, first name its domain (AI, once). Then compare the analyst table
    with the kept one (a plain script); when there are new changes, have the
    rating_change_cause_searcher skill find their reasons (AI), and report how many."""
    def work() -> dict:
        key = f"causes:{ticker}"
        domain = name_domain(ticker) if new_asset else None
        if domain:
            JOBS.note(key, domain=domain)  # the page shows it now, before the reasons
        todo = diff(ticker, news=False).get("to_explain") or 0  # a quick count first
        if todo:
            JOBS.note(key, phase="collecting", to_explain=todo)
            todo = diff(ticker).get("to_explain") or 0  # now with the news headlines for each change
        if not todo:
            return {"state": "done", "to_explain": 0, "explained": 0, "domain": domain, "message": "no new analyst changes"}
        cli = claude_cli()
        if not cli:
            return {"state": "error", "to_explain": todo, "domain": domain,
                    "message": "Claude Code isn't installed on this computer"}
        JOBS.note(f"causes:{ticker}", phase="searching", to_explain=todo)
        budget = min(BUDGET_MAX_USD, max(BUDGET_MIN_USD, BUDGET_PER_CHANGE_USD * todo))
        prompt = (f"Use the rating_change_cause_searcher skill for {ticker}. It runs unattended in the background, "
                  "started by the investing UI after a refresh: ask no questions, and finish by saving the reasons.")
        code, result = claude_json([cli, "-p", prompt, "--permission-mode", "dontAsk", "--allowedTools", *REASON_TOOLS,
                                    "--output-format", "json", "--max-budget-usd", f"{budget:.2f}",
                                    "--no-session-persistence"], REASONS_TIMEOUT_S)
        log_run(ticker, "reasons", code, result, to_explain=todo)
        left = diff(ticker, news=False).get("to_explain") or 0
        explained = max(0, todo - left)
        if code != 0 or result.get("is_error"):
            message = f"stopped with {left} of {todo} changes still to explain"
            return {"state": "error", "to_explain": todo, "explained": explained, "left": left, "domain": domain,
                    "message": message}
        return {"state": "done", "to_explain": todo, "explained": explained, "left": left, "domain": domain,
                "message": f"explained {explained} of {todo} new analyst changes"}
    return work


def start_reasons(ticker: str, new_asset: bool = False) -> Optional[str]:
    """Start the background AI for an asset, unless it's turned off: "started", "running" or None."""
    if not AUTO_AI:
        return None
    return "started" if JOBS.start(f"causes:{ticker}", reasons_job(ticker, new_asset)) else "running"


def refresh_job(script: Path, ticker: str) -> Callable[[], dict]:
    def work() -> dict:
        code, out, err = run([sys.executable, str(script)], REFRESH_TIMEOUT_S)
        out_lines, err_lines = out.strip().splitlines(), err.strip().splitlines()
        if code == 0:
            return {"state": "done", "message": out_lines[-1] if out_lines else "updated",
                    "causes": start_reasons(ticker)}
        return {"state": "error", "message": err_lines[-1] if err_lines else f"exit code {code}"}
    return work


def describe(result: dict, ticker: str) -> str:
    """A short report of what new_page.py did, for the page's notice."""
    if result.get("restored"):
        return f"{ticker} is back, with the comparison series and settings it had before it was deleted."
    why = result.get("why") or {}
    series = "; ".join(label + (f" ({why[s]})" if why.get(s) else "")
                       for s, label in (result.get("compare") or {}).items())
    lines = [f"{result.get('name') or ticker} added."]
    if series:
        lines.append(f"Compared with: {series}.")
    lines.append(f"To change the comparison series, edit UI/asset/{slug(ticker)}_page/config.json and press Refresh.")
    return "\n".join(lines)


def add_job(ticker: str) -> Callable[[], dict]:
    """Add an asset with plain scripts: restore a deleted copy if there is one, otherwise
    create the page with comparison series picked by new_page.py's fixed rules."""
    def work() -> dict:
        if archived(ticker):
            via = "the page builder script (restored from your deleted assets)"
            cmd = [sys.executable, str(NEW_PAGE), "restore", ticker]
        else:
            via = "the page builder script (fixed rules, no AI)"
            cmd = [sys.executable, str(NEW_PAGE), "create", ticker, "--auto"]
        code, out, err = run(cmd, ADD_TIMEOUT_S)
        try:
            result = json.loads(out)
        except ValueError:
            result = {"ok": False, "error": (out.strip() or err.strip())[-3000:] or f"exit code {code}"}
        added = pipeline_for(ticker) is not None
        if result.get("ok") and added:
            return {"state": "done", "added": True, "via": via, "message": describe(result, ticker),
                    "causes": start_reasons(ticker, new_asset=True)}
        message = result.get("error") or "\n".join(result.get("first_update") or []) or f"exit code {code}"
        return {"state": "error", "added": added, "via": via, "message": message}
    return work


class Jobs:
    """Background jobs keyed by "<job>:<ticker>", each with its latest status."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status: dict = {}

    def get(self, key: str) -> dict:
        with self.lock:
            return dict(self.status.get(key, {"state": "idle"}))

    def busy(self, prefix: str) -> bool:
        with self.lock:
            return any(k.startswith(prefix) and v.get("state") == "running" for k, v in self.status.items())

    def note(self, key: str, **fields) -> None:
        """Add progress details to a running job's status."""
        with self.lock:
            if key in self.status:
                self.status[key].update(fields)

    def start(self, key: str, work: Callable[[], dict]) -> bool:
        with self.lock:
            if self.status.get(key, {}).get("state") == "running":
                return False
            self.status[key] = {"state": "running", "started_at": now()}
        threading.Thread(target=self._run, args=(key, work), daemon=True).start()
        return True

    def _run(self, key: str, work: Callable[[], dict]) -> None:
        try:
            result = work()
        except subprocess.TimeoutExpired as exc:
            result = {"state": "error", "message": f"it took longer than {exc.timeout:.0f} seconds"}
        except Exception as exc:
            result = {"state": "error", "message": str(exc)}
        first_line = (result.get("message") or "").strip().splitlines()[:1]
        print(f"{datetime.now():%H:%M:%S} {key}: {result['state']} - {first_line[0] if first_line else ''}")
        with self.lock:
            self.status[key] = dict(self.status.get(key, {}), finished_at=now(), **result)


JOBS = Jobs()


class Handler(SimpleHTTPRequestHandler):
    jobs = JOBS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, fmt, *args):  # keep the console for job results
        pass

    def end_headers(self):
        if self.path.startswith(("/data/", "/api/")):
            self.send_header("Cache-Control", "no-store")
        else:
            # Make the browser re-check the page and its files on every load,
            # so a normal reload always picks up changes to the UI.
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _local(self) -> bool:
        """Reject requests addressed to another host name (DNS-rebinding guard)."""
        return (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query(self) -> dict:
        return parse_qs(urlparse(self.path).query)

    def _ticker(self, required: bool = False) -> Optional[str]:
        values = self._query().get("ticker")
        if not values:
            return None if required else "IREN"
        ticker = values[0].strip().upper()
        return ticker if TICKER_RE.match(ticker) else None

    def do_GET(self):
        path = urlparse(self.path).path
        if not self._local():
            return self._json(403, {"error": "local access only"})
        if path == "/api/status":
            ticker = self._ticker()
            if not ticker:
                return self._json(400, {"error": "bad ticker"})
            asked = (self._query().get("job") or [""])[0]
            job = asked if asked in ("add", "causes") else "refresh"
            return self._json(200, dict(self.jobs.get(f"{job}:{ticker}"), ticker=ticker, job=job,
                                        registered=pipeline_for(ticker) is not None))
        if not (path in SERVED or path.startswith(SERVED_DIRS)):
            return self._json(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        # The custom header can't be sent cross-site without a CORS preflight,
        # which this server never approves, so other web pages can't start jobs.
        if not self._local() or self.headers.get("X-Requested-With") != "investing-ui":
            return self._json(403, {"error": "only the investing UI on this computer can do that"})
        path = urlparse(self.path).path
        if path not in ("/api/refresh", "/api/assets"):
            return self._json(404, {"error": "not found"})
        ticker = self._ticker(required=True)
        if not ticker:
            return self._json(400, {"error": "bad ticker: use letters, digits, '.' or '-', e.g. NVDA, BRK-B, TEVA.TA"})
        if path == "/api/refresh":
            script = pipeline_for(ticker)
            if not script:
                return self._json(404, {"error": f"{ticker} isn't in your watchlist; add it first"})
            started = self.jobs.start(f"refresh:{ticker}", refresh_job(script, ticker))
            return self._json(202 if started else 409, dict(self.jobs.get(f"refresh:{ticker}"), ticker=ticker))
        if pipeline_for(ticker):
            return self._json(409, {"error": f"{ticker} is already in your watchlist", "registered": True, "ticker": ticker})
        if self.jobs.busy("add:"):
            return self._json(409, {"error": "another asset is being added; try again when it finishes", "ticker": ticker})
        self.jobs.start(f"add:{ticker}", add_job(ticker))
        return self._json(202, dict(self.jobs.get(f"add:{ticker}"), ticker=ticker))

    def do_DELETE(self):
        if not self._local() or self.headers.get("X-Requested-With") != "investing-ui":
            return self._json(403, {"error": "only the investing UI on this computer can do that"})
        if urlparse(self.path).path != "/api/assets":
            return self._json(404, {"error": "not found"})
        ticker = self._ticker(required=True)  # never fall back to a default here
        if not ticker:
            return self._json(400, {"error": "say which asset to delete: ?ticker=..."})
        if not pipeline_for(ticker):
            return self._json(404, {"error": f"{ticker} isn't in your watchlist"})
        if any(self.jobs.get(f"{job}:{ticker}").get("state") == "running" for job in ("refresh", "add", "causes")):
            return self._json(409, {"error": f"{ticker} is updating right now; try again when it finishes"})
        code, out, err = run([sys.executable, str(NEW_PAGE), "delete", ticker], 60)
        try:
            result = json.loads(out)
        except ValueError:
            result = {"ok": False, "error": (err or out).strip()[-500:] or f"exit code {code}"}
        print(f"{datetime.now():%H:%M:%S} delete:{ticker}: {'done' if result.get('ok') else 'error'}")
        return self._json(200 if code == 0 and result.get("ok") else 500, result)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, address reuse lets a second server bind a busy port; turn it off there.
    allow_reuse_address = os.name != "nt"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the UI in the browser")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    try:
        server = Server(("127.0.0.1", args.port), Handler)
    except OSError:
        print(f"Port {args.port} is in use; the UI server is probably running already. Opening {url}")
        if args.open:
            webbrowser.open(url)
        return 0
    print(f"Investing UI: {url}")
    print("Buttons run Python scripts. In the background, Claude names a new asset's domain and finds the")
    print("reasons behind new analyst changes, only for what's new. Keep this window open while you use the page;")
    print("close it, or press Ctrl+C, to stop.")
    if args.open:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
