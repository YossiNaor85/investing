---
name: asset-page
description: Adds a stock or ETF to the investing UI. It creates the asset's page and the Python pipeline that builds and refreshes it, registers it under "Your assets", runs it once and checks the result. Use when the user asks to add, create, build or set up a page, pipeline or tracking in the UI for a ticker or company (e.g. "add NVDA", "make a page for TEVA"), or to rebuild an existing asset page.
argument-hint: "<TICKER> [--rebuild]"
shell: powershell
allowed-tools: PowerShell(.\.venv\Scripts\python.exe UI\pipeline\new_page.py *), Bash(.venv/Scripts/python.exe UI/pipeline/new_page.py *)
---

# asset-page

Adds one asset to the investing UI: a page at `UI/index.html#<TICKER>`, plus the pipeline that keeps it current. IREN was the first. Every asset follows the same pattern, so the pages stay comparable and one engine serves them all.

## What a page is made of

| Path | What it is |
|---|---|
| `UI/asset/<slug>_page/config.json` | the asset's settings: its comparison series, and why each matters |
| `UI/asset/<slug>_page/update_<slug>_page.py` | its pipeline: it calls the shared engine `UI/pipeline/asset_page.py`, and has a `customize()` hook for changes only this asset needs |
| `UI/assets.json` | "Your assets", in order (IREN first) |
| `UI/data/<TICKER>.js` and `.json` | the page's data, rewritten by every run (git-ignored) |

`<slug>` is the ticker in lowercase, with other characters turned into `_` (BRK-B → `brk_b`). The page itself is the shared `UI/index.html`, which shows any registered ticker.

## Steps

1. **Ticker.** Use `$0`, uppercased. Yahoo symbols follow two conventions:
   - share classes take a dash: `BRK-B`
   - listings outside the US carry an exchange suffix: `TEVA.TA`

   If the user named a company instead of a ticker, find the ticker and confirm it with them.
2. **Inspect.** Run `.\.venv\Scripts\python.exe UI\pipeline\new_page.py inspect <TICKER>`. Stop and tell the user if any of these hold:
   - `ok` is false: Yahoo doesn't know the symbol. Suggest the likely one.
   - `type` isn't EQUITY or ETF: ask before going on, because the page will have no company ratios.
   - `page_exists` is true but the user didn't ask to rebuild: ask whether to rebuild.
3. **Choose the comparison series.** Read `${CLAUDE_SKILL_DIR}/references/compare-series.md`. Beta and correlation are measured against these series, so pick what actually moves the stock:
   - the market (SPY for US listings)
   - the asset's domain ETF
   - at most one driver of its business

   `suggested_compare` comes from Yahoo's classification and is only a starting point. Write a short reason for each series; the page shows it.
4. **Create.** Run:

   `.\.venv\Scripts\python.exe UI\pipeline\new_page.py create <TICKER> --compare "<SYMBOL>=<Label>" --why "<SYMBOL>=<reason>" [more --compare / --why] [--note "<line under the name>"] [--rebuild]`

   - SPY is added as the market unless `--market` names another.
   - Use `--note` only for something the user said about the asset, such as why they follow it.
   - `--rebuild` rewrites the config but keeps the script and its `customize()` code. Without `--compare`, it also keeps the current series. Add `--new-script` to regenerate the script from the template; that drops any `customize()` code.

   The command registers the asset at the end of Your assets, runs the first update and prints the result. If the update fails, report the error instead of retrying in a loop.
5. **Check.** Run `.\.venv\Scripts\python.exe UI\pipeline\new_page.py check <TICKER>`, then Read the screenshots it lists and confirm:
   - the chart is drawn
   - the ratios are filled in
   - no labels collide

   `empty_values` lists the ratios Yahoo didn't provide. Gaps are normal for ETFs and young companies; tell the user which missing ones matter.
6. **Report** in a few lines:
   - the link, http://127.0.0.1:8765/#<TICKER>, and the note that `UI\link\start-investing-ui.cmd` starts the server if it isn't running (don't try to check it yourself)
   - the comparison series and why each was picked
   - any warnings, such as currency or missing data
   - the files created

## Rules

- When the UI's **Add asset** button runs this skill (headless, through `UI/server.py`), nobody can answer questions. Wherever a step says to ask, stop instead, and end with a short explanation of what's needed. The UI shows your final message.
- Only add tickers the user asked for.
- Don't edit `UI/pipeline/asset_page.py` to suit one asset; that changes every page. One-asset changes go in that asset's `customize()` (see `${CLAUDE_SKILL_DIR}/references/customizing.md`).
- If you change what the pipeline writes, follow `${CLAUDE_SKILL_DIR}/references/page-contract.md`, and update `UI/static/app.js` in the same change.
- To take an asset off the list, run `new_page.py remove <TICKER>`. It keeps the folder; delete the folder only if the user asks.
