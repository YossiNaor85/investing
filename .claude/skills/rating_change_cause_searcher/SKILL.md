---
name: rating_change_cause_searcher
description: Finds why analysts changed their rating or price target on a stock in the investing UI, and keeps the asset's analyst table, with each change's reason, in its folder. The UI's Refresh compares Yahoo's table with the kept one and runs this skill in the background on just the new changes. Use it by hand when a rating changes page shows "Not looked into yet", after a stock's page is built (the asset-page skill calls it), or when the user asks why an analyst upgraded, downgraded, started coverage or moved a target on a followed stock. Takes tickers; with none, it covers every asset in Your assets.
argument-hint: "[TICKER ...]"
allowed-tools: Bash(.venv/Scripts/python.exe UI/pipeline/rating_causes.py *), PowerShell(.venv/Scripts/python.exe UI/pipeline/rating_causes.py *), PowerShell(.\.venv\Scripts\python.exe UI\pipeline\rating_causes.py *), WebSearch, WebFetch, Edit(UI/data/_causes/**)
---

# rating_change_cause_searcher

Each stock in the investing UI has a page of analyst rating changes, `#<TICKER>/ratings`, opened from the Analysts box on its fundamental ratios page. It lists every analyst update of the past year from Yahoo, newest first: date, firm, rating, previous rating and price target. This skill fills its **Why** column with the firm's reason for each **change**:
- a new rating: an upgrade, a downgrade or new coverage
- a new price target, raised or cut

A plain reiteration, with the same rating and the same target, needs no reason.

The table is kept with the asset in `UI/asset/<slug>_page/analyst_table.json`, as it stood after the last search, with each change's reason. On every Refresh:
1. The page's update reads the kept table. It uses no AI and searches nothing.
2. The UI server runs `rating_causes.py diff`, which compares Yahoo's table with the kept one.
3. Only when there are new changes does the server start this skill in the background (Claude Code, non-interactive), on just those changes.
4. `save` adds their reasons to the kept table and updates the page.

A past change's reason doesn't change, so each change is searched once. Only the past year is kept.

## Steps

1. **Compare the tables.** Run:

   `.venv/Scripts/python.exe UI/pipeline/rating_causes.py diff $ARGUMENTS`

   With no tickers it covers every asset in Your assets. For each asset it prints `to_explain`, the number of new changes without a reason, and writes them to `UI/data/_causes/<TICKER>.pending.json`. The changes come in groups of changes days apart, because several firms moving in the same days usually react to one event. Each change has:
   - its `id`
   - its facts: date, firm, action, rating and previous rating, the target before and after, and whether the rating or the target changed
   - `headlines`: what Google News had about that firm and company within a few days. `null` means the news search was cut short; search the web for that change.

   If nothing is to explain, say so and stop. For a big backlog, add `--limit 25`. That lists only the newest groups, up to about 25 changes. Save them, then run `diff` again for the next batch.

2. **Find the event behind each group.** Read the pending file. When several firms moved within a few days, or a change came right after news, something happened:
   - the company's results or guidance
   - an investor day or user conference
   - a deal, contract or acquisition
   - a financing
   - a big price move

   Search once for it, for example `Okta results August 2026`. Note its date and the main facts, such as a beat or miss, guidance raised or cut, or the size of a deal.

3. **Find each change's reason.**
   - Start with its headlines. Many give the reason: "Wells Fargo upgrades Okta stock rating on AI growth potential", "Cantor Fitzgerald cuts IREN stock price target on delayed timeline".
   - When they don't, search the web for the firm, the company, the action and the month, for example `Mizuho Okta downgrade June 2026` or `Bernstein IREN price target November 2026`. Open the article when the snippet doesn't give the reason.
   - When nothing gives this firm's own reason but the group's event explains the timing, use the event and mark the reason inferred.

   For more than about 25 changes, split the groups among general-purpose subagents and run them in parallel. Give each subagent:
   - the pending file's path and the date ranges of its groups
   - the section "Writing a reason" below
   - its own file to write to: `UI/data/_causes/<TICKER>.found-<n>.json`

4. **Save.** Write the list (format below) to `UI/data/_causes/<TICKER>.found.json`, then run:

   `.venv/Scripts/python.exe UI/pipeline/rating_causes.py save <TICKER> UI/data/_causes/<TICKER>.found.json`

   - It takes several files too, such as the subagents' `UI/data/_causes/<TICKER>.found-*.json`.
   - It checks every entry and writes nothing if one is wrong. Fix what it lists and run it again.
   - Then it adds the reasons to the kept table and updates the page's data.

5. **Report** per asset:
   - how many reasons were reported, how many inferred, and how many have no reason found
   - anything still to explain
   - two or three of the most telling reasons, such as a downgrade, a big target cut or a new coverage

   The page shows the reasons after a browser refresh (F5).

When the UI started this skill in the background, nobody is there to answer questions. Make the calls yourself, and always finish by saving what you found.

## Writing a reason

The list is JSON, with one entry per change:

```json
[
  {"id": "2026-09-14|JP Morgan|Overweight|Underweight",
   "cause": "Double upgrade to Overweight: prices on new AI cloud contracts are rising",
   "basis": "reported", "source": "TIKR", "url": "https://..."},
  {"id": "2026-11-06|Cantor Fitzgerald|Overweight|Overweight",
   "cause": "Cut target to $47: Microsoft deployment slipped; lower 2028 EBITDA estimates",
   "basis": "reported", "source": "Investing.com", "url": "https://..."},
  {"id": "2026-03-06|BMO Capital|Outperform|Market Perform",
   "cause": "After Q4 FY26 results (Mar 4): ...",
   "basis": "inferred", "source": "Okta results release", "url": "https://..."},
  {"id": "2026-10-15|Citigroup|Buy|Buy", "cause": null}
]
```

| Field | What to put |
|---|---|
| `id` | copied exactly from the pending file |
| `cause` | the firm's reason, in one plain line under 160 characters. Lead with what changed in the firm's view, then why. Use a number only if a source gives it. |
| `basis` | `"reported"` when an article gives this firm's reason. `"inferred"` when none does, but the timing ties the change to a dated event you checked; name the event in the cause: "After Q1 FY27 results (Nov 5): …" |
| `source`, `url` | the publication and the article. A Google News link from the headlines is fine. An inferred reason can point to the event's source, such as the results release. |

Put `"cause": null` when no article gives a reason and no event explains the timing. The page then shows "No reason found". The change isn't searched again, unless it was less than four days old when you looked.

Rules:
- A reason is about the firm's decision, not the stock's move that day. "IREN Shares Rise as Northland Targets $99" says nothing about why Northland started coverage.
- Never invent a reason or a number. Inferred means a checked event, not a guess.
- Report the firm's view, not yours.
- The page shows the reason to the user as written: plain words, no file names, no mention of this skill.

## What's where

| Path | What it is |
|---|---|
| `UI/asset/<slug>_page/analyst_table.json` | the kept table with each change's reason. It moves with the asset's folder when the asset is deleted and comes back when it's restored. |
| `UI/pipeline/rating_causes.py` | `diff` and `save`: this skill's fixed steps |
| `UI/server.py` | runs `diff` after each Refresh or Add, and starts this skill when `to_explain` is above zero. `AUTO_REASONS = False` there turns that off. |
| `UI/pipeline/asset_page.py` | the page's update. `analyst_actions()` reads the kept table. |
| `UI/data/_causes/` | working files: the pending and found lists, and `<TICKER>.log`, a line per background run with its cost. `save` removes the lists once they're used. |
