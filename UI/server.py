r"""Serve the investing UI on this computer, and run its pipelines on demand.

    .venv\Scripts\python.exe UI\server.py           # http://127.0.0.1:8765/
    .venv\Scripts\python.exe UI\server.py --open    # ...and open it in the browser

The page calls three endpoints:

    POST /api/refresh?ticker=IREN   run the asset's pipeline (listed in UI/assets.json)
    POST /api/assets?ticker=RIOT    add an asset: run the asset-page skill headless
                                    (claude -p "/asset-page RIOT") from the repo root
    GET  /api/status?ticker=RIOT[&job=add]   progress of either job

Without the claude command, adding falls back to UI/pipeline/new_page.py with
its suggested comparison series. The server listens on 127.0.0.1 only, so no
other computer can reach it. It serves only the page, its static files and data/.
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
TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")
REFRESH_TIMEOUT_S = 300
ADD_TIMEOUT_S = 900
SERVED = ("/", "/index.html", "/static/", "/data/")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pipeline_for(ticker: str) -> Optional[Path]:
    """The asset's update script from UI/assets.json, or None if it isn't followed."""
    try:
        assets = json.loads((UI_DIR / "assets.json").read_text(encoding="utf-8")).get("assets", [])
    except (OSError, ValueError):
        return None
    for a in assets:
        if a.get("ticker") == ticker and a.get("pipeline"):
            script = (UI_DIR / a["pipeline"]).resolve()
            if script.is_file() and UI_DIR in script.parents:
                return script
    return None


def run(cmd: list, timeout: int) -> tuple:
    """(exit code, stdout, stderr) of a command run from the repo root."""
    proc = subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, timeout=timeout,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def refresh_job(script: Path) -> Callable[[], dict]:
    def work() -> dict:
        code, out, err = run([sys.executable, str(script)], REFRESH_TIMEOUT_S)
        out_lines, err_lines = out.strip().splitlines(), err.strip().splitlines()
        if code == 0:
            return {"state": "done", "message": out_lines[-1] if out_lines else "updated"}
        return {"state": "error", "message": err_lines[-1] if err_lines else f"exit code {code}"}
    return work


def add_job(ticker: str) -> Callable[[], dict]:
    def work() -> dict:
        claude = shutil.which("claude")
        if claude:
            via = "the asset-page skill (Claude Code, headless)"
            code, out, err = run([claude, "-p", f"/asset-page {ticker}", "--permission-mode", "dontAsk",
                                  "--output-format", "json", "--max-turns", "40"], ADD_TIMEOUT_S)
            try:
                result = json.loads(out)
                message = str(result.get("result") or "").strip()
                failed = bool(result.get("is_error")) or code != 0
            except ValueError:
                message = (out.strip() or err.strip())[-3000:]
                failed = code != 0
        else:
            via = ("the scaffolder alone, because the claude command wasn't found. The comparison series are "
                   f"unreviewed suggestions; run /asset-page {ticker} --rebuild in Claude Code to have them chosen")
            code, out, err = run([sys.executable, str(NEW_PAGE), "create", ticker, "--auto"], ADD_TIMEOUT_S)
            message = (out.strip() or err.strip())[-3000:]
            failed = code != 0
        added = pipeline_for(ticker) is not None
        state = "done" if added else ("error" if failed else "stopped")
        return {"state": state, "added": added, "via": via, "message": message or f"exit code {code}"}
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


class Handler(SimpleHTTPRequestHandler):
    jobs = Jobs()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, fmt, *args):  # keep the console for job results
        pass

    def end_headers(self):
        if self.path.startswith(("/data/", "/api/")):
            self.send_header("Cache-Control", "no-store")
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

    def _ticker(self) -> Optional[str]:
        ticker = (self._query().get("ticker") or ["IREN"])[0].strip().upper()
        return ticker if TICKER_RE.match(ticker) else None

    def do_GET(self):
        path = urlparse(self.path).path
        if not self._local():
            return self._json(403, {"error": "local access only"})
        if path == "/api/status":
            ticker = self._ticker()
            if not ticker:
                return self._json(400, {"error": "bad ticker"})
            job = "add" if (self._query().get("job") or [""])[0] == "add" else "refresh"
            return self._json(200, dict(self.jobs.get(f"{job}:{ticker}"), ticker=ticker, job=job,
                                        registered=pipeline_for(ticker) is not None))
        if not (path in SERVED[:2] or path.startswith(SERVED[2:])):
            return self._json(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        # The custom header can't be sent cross-site without a CORS preflight,
        # which this server never approves, so other web pages can't start jobs.
        if not self._local() or self.headers.get("X-Requested-With") != "investing-ui":
            return self._json(403, {"error": "only the investing UI on this computer can do that"})
        path = urlparse(self.path).path
        ticker = self._ticker()
        if path not in ("/api/refresh", "/api/assets"):
            return self._json(404, {"error": "not found"})
        if not ticker:
            return self._json(400, {"error": "bad ticker: use letters, digits, '.' or '-', e.g. NVDA, BRK-B, TEVA.TA"})
        if path == "/api/refresh":
            script = pipeline_for(ticker)
            if not script:
                return self._json(404, {"error": f"{ticker} isn't in Your assets; add it first"})
            started = self.jobs.start(f"refresh:{ticker}", refresh_job(script))
            return self._json(202 if started else 409, dict(self.jobs.get(f"refresh:{ticker}"), ticker=ticker))
        if pipeline_for(ticker):
            return self._json(409, {"error": f"{ticker} is already in Your assets", "registered": True, "ticker": ticker})
        if self.jobs.busy("add:"):
            return self._json(409, {"error": "another asset is being added; try again when it finishes", "ticker": ticker})
        self.jobs.start(f"add:{ticker}", add_job(ticker))
        return self._json(202, dict(self.jobs.get(f"add:{ticker}"), ticker=ticker))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, address reuse lets a second server bind a busy port; turn it off there.
    allow_reuse_address = os.name != "nt"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the UI in the browser")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/#IREN"
    try:
        server = Server(("127.0.0.1", args.port), Handler)
    except OSError:
        print(f"Port {args.port} is in use; the UI server is probably running already. Opening {url}")
        if args.open:
            webbrowser.open(url)
        return 0
    print(f"Investing UI: {url}")
    print(f"Adding assets runs: {shutil.which('claude') or 'the scaffolder only (claude command not found)'}")
    print("Keep this window open while you use the page. Close it, or press Ctrl+C, to stop.")
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
