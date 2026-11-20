r"""Pipeline for the AAPL page of the investing UI (Apple Inc.).

Fetches the latest data for AAPL and rewrites UI/data/AAPL.js and .json,
which UI/index.html#AAPL shows. The shared engine in UI/pipeline/asset_page.py
does the work; this asset's settings are in config.json next to this file.

Run from the repo root:

    .venv\Scripts\python.exe UI\asset\aapl_page\update_aapl_page.py             # one update
    .venv\Scripts\python.exe UI\asset\aapl_page\update_aapl_page.py --every 15  # every 15 minutes until stopped

The page's Refresh button runs this script through UI/server.py.
Created by the asset-page skill on 2026-11-20.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The UI folder is the nearest parent holding the shared engine, wherever this folder sits.
UI_DIR = next(p for p in HERE.parents if (p / "pipeline" / "asset_page.py").is_file())
sys.path.insert(0, str(UI_DIR))

from pipeline import asset_page  # noqa: E402


def customize(data: dict, ctx: dict) -> dict:
    """Changes for AAPL only. Runs after the standard build; return the data.

    ctx holds "config", "info" (Yahoo's company data), "history" (2 years of
    daily bars), "intraday" (the latest session's 1-minute bars) and "compare"
    (daily closes of the comparison series).
    See .claude/skills/asset-page/references/customizing.md.
    """
    return data


if __name__ == "__main__":
    sys.exit(asset_page.main(HERE / "config.json", customize=customize))
