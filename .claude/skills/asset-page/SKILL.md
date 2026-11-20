---
name: asset-page
description: Adds a stock or ETF to the investing UI. It creates the asset's page and the Python pipeline that builds and refreshes it, registers it under My watchlist, runs it once and checks the result. Use when the user asks to add, create, build or set up a page, pipeline or tracking in the UI for a ticker or company (e.g. "add NVDA", "make a page for TEVA"), or to rebuild an existing asset page.
argument-hint: "<TICKER> [--rebuild]"
shell: powershell
allowed-tools: PowerShell(.\.venv\Scripts\python.exe UI\pipeline\new_page.py *), Bash(.venv/Scripts/python.exe UI/pipeline/new_page.py *)
---

# asset-page

Adds one asset to the investing UI: a page at `UI/index.html#<TICKER>`, plus the pipeline that keeps it current. IREN was the first. Every asset follows the same pattern, so the pages stay comparable and one engine serves them all.

## What a page is made of

| Path | What it is |
|---|---|
| `UI/asset/<slug>_page/config.json` | the asset's settings: its comparison series and why each matters, and its domain |
| `UI/asset/<slug>_page/update_<slug>_page.py` | its pipeline: it calls the shared engine `UI/pipeline/asset_page.py`, and has a `customize()` hook for changes only this asset needs |
| `UI/asset/<slug>_page/analyst_table.json` | the kept analyst table, with each change's reason (stocks). `rating_change_cause_searcher` and `UI/pipeline/rating_causes.py` keep it; the pipeline only reads it. |
| `UI/assets.json` | My watchlist (the page sorts it by domain, then A to Z) |
| `UI/data/<TICKER>.js` and `.json` | the page's data, rewritten by every run (git-ignored) |

`<slug>` is the ticker in lowercase, with other characters turned into `_` (BRK-B → `brk_b`). The page itself is the shared `UI/index.html`, which shows any registered ticker:

| Address | What it shows |
|---|---|
| `#` | the site's first page: My thoughts (`UI/my_thoughts.md`) and My watchlist |
| `#watchlist` | My watchlist: a table of Ticker, Asset, Domain and Remove (a ✕), sorted by domain, then A to Z |
| `#<TICKER>` | the asset's first page: headline tiles, plus a box for each section |
| `#<TICKER>/graphs/1Y` | the graphs (also `/3M` and `/1D`) and the econometric measures |
| `#<TICKER>/ratios` | the fundamental ratios |
| `#<TICKER>/ratings` | the analyst rating changes of the past year, with reasons; opened from the Analysts box on the ratios page |
| `#<TICKER>/news`, `/info`, `/analyst`, `/sentiment` | empty for now |

## Steps

1. **Ticker.** Use `$0`, uppercased. Yahoo symbols follow two conventions:
   - share classes take a dash: `BRK-B`
   - listings outside the US carry an exchange suffix: `TEVA.TA`

   If the user named a company instead of a ticker, find the ticker and confirm it with them.
2. **Inspect.** Run `.\.venv\Scripts\python.exe UI\pipeline\new_page.py inspect <TICKER>`. Stop and tell the user if any of these hold:
   - `ok` is false: Yahoo doesn't know the symbol. Suggest the likely one.
   - `type` isn't EQUITY or ETF: ask before going on, because the page will have no company ratios.
   - `page_exists` is true but the user didn't ask to rebuild: ask whether to rebuild.

   If `archived` is true, the asset was deleted before. Run `.\.venv\Scripts\python.exe UI\pipeline\new_page.py restore <TICKER>` instead of creating it: that brings back its earlier settings and `customize()` code. Then go to step 5. Only build a fresh page if the user asked for one.
3. **Choose the comparison series.** Read `${CLAUDE_SKILL_DIR}/references/compare-series.md`. Beta and correlation are measured against these series, so pick what actually moves the stock:
   - the market (SPY for US listings)
   - the asset's domain ETF
   - at most one driver of its business

   `suggested_compare` comes from Yahoo's classification and is only a starting point. Write a short reason for each series; the page shows it.

   Also name the asset's **domain**: its business theme in one to three words, as My watchlist shows it, such as Data centers, Cybersecurity, Semiconductors or Bitcoin mining. Take it from the company's own description (`business` in the inspect output), not from Yahoo's sector and industry, which lag behind pivots: IREN and Cipher build AI data centers, but Yahoo still files IREN under Capital Markets. Reuse a domain the watchlist already has when it fits.
4. **Create.** Run:

   `.\.venv\Scripts\python.exe UI\pipeline\new_page.py create <TICKER> --compare "<SYMBOL>=<Label>" --why "<SYMBOL>=<reason>" [more --compare / --why] --domain "<domain>" [--note "<line under the name>"] [--rebuild]`

   - SPY is added as the market unless `--market` names another.
   - Use `--note` only for something the user said about the asset, such as why they follow it.
   - `--rebuild` rewrites the config but keeps the script and its `customize()` code. Without `--compare`, it also keeps the current series. Add `--new-script` to regenerate the script from the template; that drops any `customize()` code.

   The command adds the asset to My watchlist, runs the first update and prints the result. If the update fails, report the error instead of retrying in a loop.
5. **Check.** Run `.\.venv\Scripts\python.exe UI\pipeline\new_page.py check <TICKER>`, then Read the screenshots it lists and confirm:
   - the first page shows the six boxes
   - the graphs are drawn (1 year and 1 day)
   - the ratios page is filled in
   - the rating changes page lists the analyst updates (stocks)
   - no labels collide

   `empty_values` lists the ratios Yahoo didn't provide. Gaps are normal for ETFs and young companies; tell the user which missing ones matter.
6. **Reasons for the analyst changes.** For a stock, invoke the `rating_change_cause_searcher` skill with the ticker. It finds why each change of rating or price target of the past year happened and keeps the table, with the reasons, in the asset's folder. Every Refresh reads it, and later refreshes send only new changes to the skill. Skip this for ETFs: they have no analyst ratings.
7. **Report** in a few lines:
   - the link, http://127.0.0.1:8765/#<TICKER>, and the note that `UI\link\start-investing-ui.cmd` starts the server if it isn't running (don't try to check it yourself)
   - the comparison series and why each was picked
   - any warnings, such as currency or missing data
   - what the reasons show, such as a recent downgrade or a big target cut
   - the files created

## Rules

- The UI's **Add asset** button doesn't use this skill. It runs `new_page.py create <TICKER> --auto` (or `restore`), which picks the comparison series by fixed rules. Use this skill when the user wants Claude to choose the series or customize a page; `--rebuild` with your own `--compare` replaces the automatic choice. Once the page is built, the UI server works in the background. Claude names the asset's domain once from the company's description (`UI/pipeline/asset_domain.py`, no tools), then `rating_change_cause_searcher` finds the reasons behind its analyst changes. Those are the only AI runs the buttons start; `AUTO_AI = False` in `UI/server.py` turns them off.
- Only add tickers the user asked for.
- Don't edit `UI/pipeline/asset_page.py` to suit one asset; that changes every page. One-asset changes go in that asset's `customize()` (see `${CLAUDE_SKILL_DIR}/references/customizing.md`).
- If you change what the pipeline writes, follow `${CLAUDE_SKILL_DIR}/references/page-contract.md`, and update `UI/static/app.js` in the same change.
- To delete an asset, which is what the UI's ✕ button does, run `new_page.py delete <TICKER>`. It moves the asset's folder to `UI/asset/_deleted/` and removes its data files. `new_page.py restore <TICKER>` brings it back. `new_page.py remove <TICKER>` only takes it off the list and leaves the files in place. Empty `_deleted/` only if the user asks.
