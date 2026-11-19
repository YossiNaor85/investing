r"""Serve the investing UI on this computer, and run its updater on demand.

    .venv\Scripts\python.exe UI\server.py           # http://127.0.0.1:8765/
    .venv\Scripts\python.exe UI\server.py --open    # ...and open it in the browser

The page's Refresh button calls POST /api/refresh?ticker=IREN. That runs the
asset's pipeline (listed in UI/assets.json, e.g. UI/iren_page/update_iren_page.py)
in the background, and GET /api/status reports its progress. The server
listens on 127.0.0.1 only, so no other computer can reach it. It serves only
the page, its static files and data/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

UI_DIR = Path(__file__).resolve().parent
REPO_DIR = UI_DIR.parent
TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")
TIMEOUT_S = 300
SERVED = ("/", "/index.html", "/static/", "/data/")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pipeline_for(ticker: str):
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


class Jobs:
    """One background update per ticker at a time, with its latest status."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status: dict = {}

    def get(self, ticker: str) -> dict:
        with self.lock:
            return dict(self.status.get(ticker, {"state": "idle"}))

    def start(self, ticker: str, script: Path) -> bool:
        with self.lock:
            if self.status.get(ticker, {}).get("state") == "running":
                return False
            self.status[ticker] = {"state": "running", "started_at": now()}
        threading.Thread(target=self._run, args=(ticker, script), daemon=True).start()
        return True

    def _run(self, ticker: str, script: Path) -> None:
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(REPO_DIR), capture_output=True, timeout=TIMEOUT_S,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
            out = proc.stdout.decode("utf-8", "replace").strip().splitlines()
            err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            if proc.returncode == 0:
                result = {"state": "done", "message": out[-1] if out else "updated"}
            else:
                result = {"state": "error", "message": err[-1] if err else f"exit code {proc.returncode}"}
        except subprocess.TimeoutExpired:
            result = {"state": "error", "message": f"the update took longer than {TIMEOUT_S} seconds"}
        except Exception as exc:
            result = {"state": "error", "message": str(exc)}
        print(f"{datetime.now():%H:%M:%S} refresh {ticker}: {result['state']} - {result['message']}")
        with self.lock:
            self.status[ticker] = dict(self.status.get(ticker, {}), finished_at=now(), **result)


class Handler(SimpleHTTPRequestHandler):
    jobs = Jobs()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, fmt, *args):  # keep the console for refresh results
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

    def _ticker(self):
        query = parse_qs(urlparse(self.path).query)
        ticker = (query.get("ticker") or ["IREN"])[0].upper()
        return ticker if TICKER_RE.match(ticker) else None

    def do_GET(self):
        path = urlparse(self.path).path
        if not self._local():
            return self._json(403, {"error": "local access only"})
        if path == "/api/status":
            ticker = self._ticker()
            if not ticker:
                return self._json(400, {"error": "bad ticker"})
            return self._json(200, dict(self.jobs.get(ticker), ticker=ticker))
        if not (path in SERVED[:2] or path.startswith(SERVED[2:])):
            return self._json(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        # The custom header can't be sent cross-site without a CORS preflight,
        # which this server never approves, so other web pages can't trigger runs.
        if not self._local() or self.headers.get("X-Requested-With") != "investing-ui":
            return self._json(403, {"error": "refresh is only allowed from the investing UI on this computer"})
        if urlparse(self.path).path != "/api/refresh":
            return self._json(404, {"error": "not found"})
        ticker = self._ticker()
        if not ticker:
            return self._json(400, {"error": "bad ticker"})
        script = pipeline_for(ticker)
        if not script:
            return self._json(404, {"error": f"{ticker} isn't in Your assets; add it with /asset-page {ticker}"})
        started = self.jobs.start(ticker, script)
        return self._json(202 if started else 409, dict(self.jobs.get(ticker), ticker=ticker))


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
