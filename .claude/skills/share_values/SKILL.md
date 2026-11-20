---
name: share_values
description: Builds and maintains the Share values pages of each stock in the investing UI. It values one share by each fundamental in the last quarterly report (net cash, tangible book, book value, revenue, earnings, EBITDA, free cash flow), from the bears' floors to the bulls' growth multiples. Each value says which side argues for it and the market mood that would take the price there. It's deterministic, with no AI: every asset's update builds it, so every asset added gets it. Use it to check or explain an asset's share values, to apply an expert's review of the bull/bear dictionary (sides, multiples, reasons), or to add a valuation method.
argument-hint: "[TICKER]"
allowed-tools: Bash(.venv/Scripts/python.exe UI/pipeline/share_values.py *), PowerShell(.venv/Scripts/python.exe UI/pipeline/share_values.py *)
---

# share_values

Each stock in the investing UI has a **Share values** box on its first page, right after Fundamental ratios. It opens `#<TICKER>/values`, a page with two boxes:

| Box | Page | What it is |
|---|---|---|
| Last quarterly report | `#<TICKER>/values-report` | The table this skill covers. Deterministic: no AI. |
| News projections | `#<TICKER>/values-news` | Coming soon: values implied by the news, such as guidance, deals and forecasts. It will be a separate AI skill. |

## How a value is made

Each row is one fundamental per share from the last quarterly report, times one multiple. The rows are sorted from the lowest value to the highest, with today's price in its place among them.
- **Balance sheet items** (net cash, book values) are taken at the quarter's end.
- **Flows** (revenue, earnings, EBITDA, free cash flow) cover the last four quarters. The bulls' revenue pace is the last quarter times four.
- **Per-share figures** use the report's own share count at the quarter's end, so every number comes from the same report. Don't divide by today's share count: shares issued after the quarter brought cash that isn't in that quarter's equity yet.
- **EBITDA values** are an enterprise value (EBITDA times the multiple) minus net debt. With heavy debt they can go below zero, which means debt takes everything.
- **Skipped fundamentals:** one that is zero or negative over the period (a loss, cash burn) gives no value and is listed as skipped.
- **Live multiples:** the S&P 500's and the sector's P/E are live from Yahoo. They come from the market series (SPY) and the asset's first comparison series that is an ETF.

**The bull/bear dictionary** is `UI/pipeline/bull_bear_dictionary.json`. For every value it holds:
- the fundamental and the multiple
- the side: bears, neutral or bulls
- the market mood shown in the table
- why that side, for the expert

It's the only place these links live, so they're the same for every asset. An expert reviews `${CLAUDE_SKILL_DIR}/references/bull-bear-dictionary.md`, which is generated from it.

## Steps

**Check an asset:** run `.venv/Scripts/python.exe UI/pipeline/share_values.py <TICKER>`. It prints the table: value, distance from today's price, side, fundamental per share and multiple. Compare the per-share figures with the company's report when something looks off.

**Apply an expert's review:**
1. Edit `UI/pipeline/bull_bear_dictionary.json`: the side, multiple, mood text or reason of a value.
2. Refresh the review copy: `.venv/Scripts/python.exe UI/pipeline/share_values.py --dictionary`, saved under the header of `${CLAUDE_SKILL_DIR}/references/bull-bear-dictionary.md`.
3. Run an asset's update, or press Refresh, to see the change. Every other asset picks it up on its next update.

**Add a valuation method:**
1. Add the fundamental to `report_values()` and `FUNDAMENTALS` in `UI/pipeline/share_values.py`.
2. Add its values to the dictionary, with a side and a reason for each.
3. Keep `UI/static/app.js` and the page contract (`.claude/skills/asset-page/references/page-contract.md`, `share_values`) in step.

## Rules

- No AI in this table: it must come out the same every time from the same report.
- Change a side only when the user or their expert asks. The dictionary is what the expert validates.
- The page shows the mood text to the user as written: plain words, no file names.
