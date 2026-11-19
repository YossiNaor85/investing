# Plan: `asset-news` skill (web scraper for news on one asset, given its ticker)

**Status:** draft 1, 2026-11-19 · sources (§5) and skill mechanics (§10) checked 2026-11-19; a few items need a hands-on test (§16)
**Requirements:** `thoughts_on_the_market.docx` ("Connect the dots")
**Related plans:** `plan_domains_and_asset_of_interest_per_period_time.md` (`domain-scout`: which tickers get run) · `plan_graph_macro_domain_trend_in_markets.md` (risk-on/off graph) · `plan_report_creator.md` (daily report)

---

## 1. Goal

`/asset-news NVDA` collects everything published that could move NVDA. It looks at three levels: the company, its domain, and the macro backdrop. It removes duplicates, scores each story, stores it, and writes a dated digest with sources. Run every day, it builds up a history.

In the doc's words this is *"an analyst that maps all the relevant sources of news, indicators, analysts, etc. to get data and engineer it on a daily basis."* The rest of the platform builds on its output:

| Consumer | What it takes from here |
|---|---|
| Calendar | future-dated events from release schedules and from the news |
| Retrospective analysis ("connect the dots") | what was known, and when, before each price move |
| Risk-on/off graph | the information side; prices are the confirmation |
| Daily report | top stories, multi-day trend stories, what's coming |

**Not in this skill:**
- price charts and the regime graph
- picking the watchlist
- in-depth financial analysis of 10-Q/10-K (a separate skill later; this one detects and summarizes them)
- trading decisions

## 2. Design principles
1. **Each asset gets its own source map.** The doc says *"each asset has its own areas of important data."* The first run builds an asset profile (§4) that decides what to collect, and you review it.
2. **Scripts collect, Claude judges.** Python collectors do the fetching. That is cheap, repeatable and testable, and it leaves an auditable history. Claude does the analyst work:
   - drafting the profile
   - judging relevance, level and weight
   - pulling out dates
   - explaining moves
   - writing the digest
   - running targeted web searches where the collectors come up short

   Web search alone would be slow, expensive, not reproducible, and useless for backtests.
3. **Primary sources first.** Filings, company releases, central banks and government data carry the signal. Most free "stock news" is SEO rewriting ("3 stocks to buy now"), so it is down-weighted or blocked.
4. **Never lose what was known when.** Items are append-only. Each one keeps the publisher's timestamp and the time we first saw it. That keeps look-ahead bias out of the retrospective analysis, and it lets us replay any past day (`--as-of`).
5. **Collect once, link to many.** Macro and domain stories are collected once a day and linked to every ticker they touch. With 10–50 tickers in 5–10 domains, collecting per ticker would multiply both cost and duplicates.
6. **Thin skill, reusable code.** Collectors and storage live in a normal Python package (`src/investing/news/`), not in the skill folder. That way the scheduler, the report and the graph can use them without Claude. The skill orchestrates the code and adds judgment.

## 3. One run, step by step

```
/asset-news NVDA [--since DATE] [--as-of DATE] [--refresh-profile] [--backfill 90d]

1 resolve       ticker → identity: CIK, name, aliases, exchange, share classes, other listings, sector
2 profile       load assets/profiles/NVDA.yaml; Claude drafts it on the first run or with --refresh-profile
3 collect       run the collectors the profile enables, incrementally since the last run;
                macro and domain layers are reused if today's shared pass already ran
4 normalize     common schema → canonical URLs → story clusters → market-session tags
5 price check   split each session's move into market / domain / own; flag abnormal ones → "why?"
6 analyze       Claude scores new stories (references/weighting.md), extracts dated events,
                and searches the web for flagged moves the collected news doesn't explain
7 store+digest  scores into the DB; digest → data/digests/NVDA/2026-11-19.md
```

- Steps 1, 3, 4, 5 and the storage half of 7 are CLI commands (`python -m investing.news …`), so collection can also run on a timer without Claude.
- Steps 2 and 6, and writing the digest, are Claude's.
- `--as-of` replays a past day using only what had been seen by then. Evals (§12) and the retrospective analysis use it.

## 4. The asset profile

`assets/profiles/<TICKER>.yaml` is kept in git because it is curated knowledge. To draft it, Claude reads the latest 10-K:
- Item 1: business, competition, major customers
- Item 1A: risk factors, which name the regulators and macro sensitivities
- Item 7: MD&A

It adds the company's IR site and web research, then you review the draft. Refresh it quarterly, or after a big change such as an acquisition, a new segment or a new regulator. Phase 4 checks the peer and dependency lists against actual return correlations, including anti-correlated assets.

```yaml
# illustrative only, not researched
ticker: NVDA
identity:
  name: NVIDIA Corporation
  aliases: [Nvidia]
  cik: "0001045810"
  exchange: NASDAQ
  other_listings: []                   # e.g. TEVA → TEVA.TA; TSM → 2330.TW
  newsroom: https://nvidianews.nvidia.com
domain:
  name: semiconductors / AI accelerators
  etfs: [SMH, SOXX]
  peers: [AMD, AVGO, INTC, MRVL]
supply_chain:
  suppliers: [TSM, MU, "000660.KS"]    # foundry, HBM memory
  customers: [MSFT, AMZN, GOOGL, META, ORCL]   # hyperscaler capex = demand
dependency_domains: [data-center power, HBM memory, advanced packaging]
macro_drivers: [real rates, US–China export controls, tariffs, AI capex cycle]
regulators: [US Commerce (BIS), USTR, China MOFCOM/SAMR, EU Commission]
people: ["Jensen Huang (CEO)"]
outside_voices: [US President, Commerce Secretary]
recurring_events: [own earnings, GTC conference, TSMC monthly revenue, hyperscaler earnings]
prediction_markets: [chip export controls, semiconductor tariffs, FOMC decisions]
search_terms:
  include: [Nvidia, Blackwell, Rubin, CUDA, "Jensen Huang"]
  exclude: []                          # disambiguation: ON needs "onsemi", excludes "turn on"
alt_data: {hiring: true, social: ceo_only, weather: false, shipping: false, satellite: false}
sources: {extra_rss: [], blocked: []}
level_multipliers: {macro: 1.0, domain: 0.8, company: 0.6}   # doc's order; calibrated in Phase 4
reviewed: false
```

## 5. Sources by level

Phase = when the source gets added (§13). Access details were checked on 2026-11-19 (§16.2). The sector sources and positioning data will be checked when their phase starts. Most free tiers (Yahoo, Finnhub, Massive, Tiingo) allow personal use only, with no redistribution (§15).

### Company (per ticker)

| Source | What it gives | Access | Phase |
|---|---|---|---|
| SEC EDGAR | 8-K, where the item codes say what happened (2.02 results, 5.02 executive change, 1.01/2.01 deals, 4.02 restatement, 3.01 delisting notice), with the earnings release attached as exhibit 99.1; 10-Q/10-K; Form 4 insider trades; 13D/13G holders; S-1/S-3/424B offerings (dilution); 6-K/20-F for foreign issuers | official JSON and Atom feeds plus full-text search; free, no key; ≤10 requests/s; User-Agent with name and email required | 1 |
| Company newsroom | press releases, events, guidance | the company's own RSS where offered, else a polite page fetch | 1 |
| Newswires (PR Newswire, Business Wire, GlobeNewswire) | press releases from companies without a usable newsroom feed | industry/subject RSS only, no per-company feeds, so we filter by name; Business Wire and GlobeNewswire block some bots | 1 |
| Google News RSS search | broad coverage, including headlines from paywalled outlets; regional and language editions | unofficial, free; `when:1d` works; query by name and aliases, never the bare ticker; can return 429 or a CAPTCHA; links are opaque Google tokens (§14) | 1 |
| Yahoo Finance (`yfinance`; 1.2 on our Python 3.9, §10.2) | headlines, earnings dates, consensus estimates, analyst up/downgrades, daily prices for the price check | unofficial; Yahoo allows personal use only; unpublished throttling | 1 |
| Finnhub company-news | news tagged with tickers, 1 year back (North America only); earnings calendar | free key, 60 calls/min; personal use only. Fallback: Marketaux (free, 100 calls/day, 3 articles per call) | 1 |
| Massive (formerly Polygon.io) news | ticker-tagged news with per-ticker sentiment, ~2 years back | free key, 5 calls/min | 4 (backfill) |
| GDELT DOC API | global multilingual news with tone; non-US coverage | free, no key; searchable back to 2017; ≤250 articles per query; ~1 request per 5 s; names only, no tickers. Degraded in Nov 2026 (missing days), so it's optional until it recovers | 2 |
| Official sector sources, per profile | biotech: ClinicalTrials.gov, openFDA · government contractors: USAspending · autos: NHTSA recalls · telecom: FCC | free official APIs | 2–3 |
| Earnings calls | transcripts: management tone, guidance details | paid (FMP has them only on its top plan); some free on company IR sites | 5 |
| Positioning | 13F institutional holdings (quarterly, ~45-day lag); short interest (twice a month) | SEC 13F data sets; FINRA | 5 |
| Hiring | open roles over time: expansion or freeze | public job-board APIs, no auth (Greenhouse, Lever, Ashby); others by page fetch | 5 |
| Social | company and CEO posts; chatter on $TICKER | Bluesky (free; search needs an app-password login); X is pay-per-use (§15). Reddit and StockTwits are closed to new developers | 5 |

### Domain (per domain, shared by its tickers)

| Source | What it gives | Access | Phase |
|---|---|---|---|
| Peers, suppliers, customers | their high-impact events only: earnings, guidance, 8-K items, big deals (a hyperscaler raising capex moves NVDA) | the company collectors, filtered by event type | 2 |
| Domain ETFs | domain-wide headlines | news search on the ETF + issuer pages | 2 |
| Regulators | rules, export controls, approvals, antitrust | Federal Register API by agency (free, no key; the website blocks scrapers, the API is the approved route); regulators' press RSS | 2 |
| Legislation | bills and votes that touch the domain | congress.gov API (free api.data.gov key; filters only, no keyword search, so we match bill titles ourselves) | 3 |
| Industry data + trade press | e.g. semis: SIA monthly sales, TSMC monthly revenue · energy: EIA weekly inventories, rig counts | official pages/RSS listed in the profile | 2–3 |
| Prediction markets | odds on domain events: tariffs, export rules, approvals | Polymarket (public reads, no key, keyword search) / Kalshi (public reads, no key; browse by series and tags, no keyword search) | 3 |

### Macro (once a day, shared by all tickers)

| Source | What it gives | Access | Phase |
|---|---|---|---|
| Fed (+ ECB/BoJ when relevant) | FOMC calendar, statements, minutes, speeches | federalreserve.gov RSS (policy, speeches, testimony); the FOMC calendar is an HTML page we parse | 3 |
| Economic releases | CPI, PPI, jobs, PCE, GDP, retail sales, jobless claims: dates (including upcoming) and results | FRED API (free key, 120 calls/min; release dates including upcoming ones); BLS and BEA publish ICS calendars (BEA also JSON; BLS wants a User-Agent with an email) | 3 |
| Treasury & liquidity | auctions, quarterly refunding, Fed balance sheet | Treasury and NY Fed data APIs | 3 |
| Government & politics | executive orders, tariffs, sanctions, elections, presidential posts | Federal Register, White House, OFAC, USTR. Truth Social has no public API (only a licensed business feed since 2026), so presidential posts come in through news coverage | 3 |
| Geopolitics | conflicts, attacks, supply disruptions | GDELT | 3 |
| Prediction markets | odds on Fed moves, recession, elections, shutdowns | Polymarket / Kalshi (public reads, no key) | 3 |
| Weather, shipping, flights, satellite | hurricanes (energy, insurers), heat (utilities), ship and plane traffic, activity near sites | NWS weather API: free, User-Agent required. OpenSky flights: free account, daily credits, non-commercial only. aisstream.io ships: free websocket, server-side only. Satellite imagery is heavy to process. Only where a profile asks | 5 |

### Not used, and why (checked 2026-11-19)

| Source | Why not |
|---|---|
| Full text from paywalled outlets (Bloomberg, Reuters, WSJ, FT) | their headlines arrive through Google News and RSS, and we link out |
| Seeking Alpha, LinkedIn | terms forbid scraping |
| Bing News Search API | retired Aug 11, 2025 |
| Reddit API | closing: no new access requests after Oct 31, 2026; full shutdown planned for Mar 2027 |
| StockTwits API | closed to new developers |
| Truth Social | no public API, only a licensed business feed; the unofficial tool was archived in Apr 2026 |
| ACLED (conflict data) | API needs an institutional email; GDELT covers geopolitics instead |
| Alpha Vantage news | `NEWS_SENTIMENT` is now premium-only |
| NewsAPI.org | free tier is for development only, with a 24-hour delay |
| Tiingo news, FMP transcripts | not included in the free tiers |

## 6. Data model

There are three levels:
- **item**: one article, filing or post
- **story**: the same event across sources
- **story × ticker**: what the story means for one asset

A macro story is analyzed once, and its direction is then set per asset. Oil going up is + for XOM and − for airlines.

```jsonc
// item
{"id": "hash(canonical_url)", "story_id": "s_…", "source": "sec_edgar", "tier": 1,
 "url": "…", "title": "…", "snippet": "≤300 chars", "lang": "en",
 "published_at": "2026-11-19T13:05:00Z", "first_seen_at": "2026-11-19T13:20:11Z",
 "session": "pre", "filing": {"form": "8-K", "items": ["2.02", "9.01"]}}

// story: shared analysis
{"id": "s_…", "level": "company", "event_type": "earnings", "summary": "…",
 "horizon": "days", "event_date": null, "first_seen_at": "…", "trading_days_active": 1}

// story × ticker: per-asset analysis
{"story_id": "s_…", "ticker": "NVDA", "link": "self", "relevant": true,
 "direction": "+", "impact": 4, "weight": 72, "why": "one sentence, cites item ids"}
```

**Session tags (ET):**

| Tag | Window |
|---|---|
| `pre` | 04:00–09:30 |
| `open_90` | 09:30–11:00 (the doc's institutional window) |
| `regular` | 11:00–15:30 |
| `close_30` | 15:30–16:00 |
| `after` | 16:00–20:00 |
| `closed` | nights, weekends, NYSE holidays |

Exact timestamps are kept as well. That lets the retrospective analysis test other windows too, such as the doc's first-15-minutes question.

## 7. Analyst rubric (`references/weighting.md`)

For each new story, Claude decides:

| Field | Question |
|---|---|
| relevant | Is the asset the subject, or only named in a list or a "stocks to watch" piece? |
| level + link | macro / domain / company; self, peer, supplier, customer, dependency |
| event_type | earnings, guidance, M&A, offering/dilution, buyback/dividend, insider trade, management change, legal/regulatory, product, contract win/loss, analyst rating, macro release, central bank, policy/tariff/sanction, geopolitical, supply disruption, prediction-market shift |
| direction | +, −, mixed, unclear, judged **for this asset**. A tariff on a competitor can be + for it. |
| impact 1–5 | How much can this move the asset? Judge the surprise against expectations, not the headline: a beat that was fully expected isn't news. Open-market insider buys say more than sales, which are often pre-planned. |
| horizon | days / weeks / quarters |
| event_date | Does it point to a future date (a decision, a vote, an effective date, earnings)? If so it's a calendar candidate, saved with the quoted sentence. |

**Weight (0–100)** = impact × level multiplier × credibility × novelty × time relevance × 20. All values below are starting guesses that Phase 4 calibrates.

- **Level multiplier**: the doc's order (macro > domain > company), starting at 1.0 / 0.8 / 0.6. Impact multiplies in, so a company earnings shock (impact 5) still beats routine macro news (impact 2) on its day. Phase 4 sets the multipliers per asset by regressing the asset's daily returns on SPY and on its domain ETF. That shows how much of its movement comes from the market, the domain, or the company itself. An oil major moves mostly with macro and its domain; a small biotech moves mostly on its own news.
- **Credibility**: four tiers, scored 1.0 / 0.85 / 0.6 / 0.3:
  1. official: filings, central banks, government data, company releases
  2. major wires and financial press
  3. trade press and analysts
  4. blogs, social, SEO content
- **Novelty**: the first report of a story scores 1.0; rewrites decay toward 0.2.
- **Time relevance** (from the doc): falls as a story ages or is overshadowed. Starting half-lives are ~2 trading days for `days`, ~2 weeks for `weeks` and ~2 months for `quarters`. It rises again over the ~5 trading days before the story's event_date.
- **Trend stories**: a story active on 3+ trading days is flagged. The doc says real trends take several days, because big money moves in tranches.

**Guardrails:**
- Every line in the digest cites stored item ids.
- Dates and numbers come only from source text.
- When Claude can't tell, it says "unclear" instead of guessing.

## 8. Price check: from moves to "why?"

Each recent session's return is split three ways:
- **market**: β × SPY
- **domain**: β × the domain ETF's move beyond the market
- **own**: what's left

A session is flagged when its own part is beyond ~2σ (60-day window), or when volume is above ~1.5× its 20-day average. The doc reads big volume as money entering or leaving.

The largest part says where to look:

| Largest part | Look at |
|---|---|
| own | company news |
| domain | domain news |
| market | macro |

If the collected stories don't explain a flagged move, Claude searches the web (e.g. "<company> shares <date>"). Whatever it finds is stored as `source: web_search` items and scored like everything else.

For assets that also trade elsewhere, Phase 4 adds how the other listing moved while the US was closed. The doc says other markets show what other institutions think.

Daily bars from Yahoo are enough for this, with Massive's free end-of-day data as a fallback. Later the price check should share a price store with the graph plan.

## 9. Storage

```
assets/profiles/<TICKER>.yaml        curated source maps (in git)
data/                                (git-ignored)
  news.db                            SQLite: items, stories, story_tickers, events, runs, source_health
  raw/<source>/<YYYY-MM-DD>.jsonl    responses as fetched, so parsers can be re-run
  runs/<run_id>/candidates.json      what Claude scores in step 6
  digests/<TICKER>/<YYYY-MM-DD>.md
```

- SQLite is plenty for one user and tens of tickers. Keep the SQL portable to Postgres in case this becomes a hosted platform.
- `events` feeds the calendar. `stories` and `story_tickers` feed the report and the retrospective analysis.
- Store metadata, snippets and Claude's summaries. Keep full text only where it's free to use, e.g. SEC filings.

## 10. Skill package and code

```
.claude/skills/asset-news/
  SKILL.md                 the workflow in §3, kept well under 500 lines
  references/              read only when a step needs them
    sources.md             per collector: what it gives, query pattern, limits, terms
    weighting.md           the rubric in §7 with worked examples
    profile-schema.md      profile fields and how to research each one
    digest-template.md     the layout in §10.1
  evals/                   test cases (§12)
src/investing/news/
  cli.py                   resolve | collect | price-check | candidates | apply-scores | add-item | digest-data
  resolve.py               SEC company_tickers.json → CIK; yfinance info; OpenFIGI for non-US
  profile.py               load + validate profiles
  collectors/              one module per source, one interface: fetch(query, since) → raw items
  normalize.py dedupe.py sessions.py price_check.py store.py
tests/                     parser tests on saved responses (no network)
```

The standard skill layout keeps scripts inside the skill's own `scripts/` folder. Here the code lives in `src/` instead, because the report, the graph and the scheduler need it too.

**Draft frontmatter**, checked against the Claude Code docs on 2026-11-19. Two of the rules still need a hands-on test (§16.1).

```yaml
---
name: asset-news
description: Collects, de-duplicates and weights the news that can move a stock (company; domain: peers, suppliers, customers, regulators; and macro), given its ticker, and writes a dated, sourced digest.
argument-hint: "<TICKER> [--since DATE] [--as-of DATE] [--refresh-profile] [--backfill 90d]"
disable-model-invocation: true
shell: powershell
allowed-tools: PowerShell(.\.venv\Scripts\python.exe -m investing.news *), WebSearch, WebFetch, Edit(data/**)
---
```

| Field | Why |
|---|---|
| `name` | must match the folder name: lowercase letters, digits and hyphens, up to 64 characters. It becomes the `/asset-news` command. |
| `disable-model-invocation: true` | Claude won't start a run on its own; you or the scheduler type `/asset-news`. A run collects, writes files and makes web calls, so it should be deliberate. It also takes the description out of Claude's context, so trigger tuning (§12.3) only matters if this is turned off later (§15). |
| `allowed-tools` | pre-approves these tools so the run doesn't stop for permission. It doesn't block other tools. Matching is literal from the start of the command, so the rule must match exactly what the body tells Claude to run. On Windows the PowerShell tool is the main shell, hence `PowerShell(…)`. `Write(…)` rules never match; `Edit(data/**)` covers writes. |
| `shell: powershell` | runs `!` commands (below) in PowerShell |

Unknown frontmatter keys are ignored without warning, so a typo fails silently. Check the fields in the first test.

**The body:**
- walks through §3 as short imperative steps, with a one-line reason only where the reason changes behavior (why primary sources, why first_seen, why "unclear" beats a guess). Loaded skill text stays in context for the rest of the session, so it stays short.
- takes the ticker from `$0` and the full argument string from `$ARGUMENTS`
- runs every CLI command as `.\.venv\Scripts\python.exe -m investing.news …`, spelled exactly as in `allowed-tools`
- points to reference files as `${CLAUDE_SKILL_DIR}/references/…`
- uses `!` injection only for quick context when the skill loads, e.g. the ticker's identity and whether a profile exists. A failing `!` command aborts the run, and long steps like `collect` stay as normal tool calls.
- hands Claude `candidates.json`, capped at about 60 stories after pre-filtering
- has Claude return its scores in one JSON file, which `apply-scores` stores

A later option is `context: fork`, which runs the skill in a sub-agent that doesn't see the conversation. That keeps long batch runs out of your main session.

### 10.1 Digest layout

```
# NVDA, 2026-11-19
Move −3.1% (market −0.8 · domain −2.0 · own −0.3) · volume 1.7× 20d avg · biggest part: domain
## What moved it          sourced explanation, or "unexplained"
## Top stories            weight ≥ 50, grouped macro / domain / company; direction, horizon, links
## Trend stories          active on 3+ trading days
## Coming up (14 days)    earnings, releases, decisions from `events`
## New dated events       found today → calendar
## Low confidence         items Claude couldn't settle
## Source health          collectors that failed
```

### 10.2 Environment

- **Python 3.9** (decided 2026-11-19; `.venv` runs 3.9.0). 3.9 reached end of life in October 2025, so some packages stop at older releases. A dry run on 2026-11-19 picked yfinance 1.2.0 (current: 1.8.0), numpy 2.0.2, pandas 2.3.3 and exchange_calendars 4.5.6. yfinance matters most: Yahoo changes often, and fixes only ship in new versions. Python 3.12.10 is still installed, so moving later is a quick venv rebuild.
- **Packages:** httpx, feedparser, pyyaml, pydantic, rapidfuzz (title similarity), python-dateutil, exchange_calendars (NYSE sessions and holidays), yfinance, pandas, numpy. trafilatura (article text extraction) is optional.
- **`.env`** (already git-ignored): `USER_AGENT="<name> <email>"` (SEC, BLS and the NWS weather API require one), `FRED_API_KEY`, `FINNHUB_API_KEY`. Later: `MASSIVE_API_KEY`, `DATA_GOV_API_KEY` (congress.gov), and a Bluesky app password.
- **`.gitignore` additions:** `data/` and `.claude/skills/*-workspace/`.

## 11. How we build it: the skill-creator loop

Each phase in §13 goes through the same loop:

1. **Code.** Add collectors and CLI commands, with parser tests.
2. **Skill text.** Update SKILL.md and `references/`.
3. **Test cases.** Add eval cases for what the phase adds (§12.2).
4. **Run.** Run each case twice in parallel: with the skill, and without it (a baseline where Claude only has web search). Grade the runs and aggregate a benchmark (pass rate, time, tokens). You review the outputs in the skill-creator's viewer and leave feedback.
5. **Improve.** Generalize from the feedback instead of patching single examples. If several runs reinvent the same helper, move it into the CLI. Cut instructions that cost time without improving results.
6. **Repeat** until the phase's "done when" holds.

If auto-invocation is turned on later (§15), tune the description's triggering with the skill-creator's optimizer (§12.3).

## 12. Testing and evaluation

### 12.1 Code tests

Collectors and parsers are tested against saved responses. These tests are fast and offline, and they catch it when a site changes its format.

### 12.2 Skill evals on frozen data

Live news changes daily, so evals replay a frozen snapshot: a copy of the DB and prices for a past date, run with `--as-of`. Phase 1 starts collecting for the test tickers right away, so snapshots build up from the first week. Each case is a folder in `.claude/skills/asset-news/evals/`, in the format `claude plugin eval` reads.

| Case | Situation | A good result | Phase |
|---|---|---|---|
| earnings-day | the day after the first test ticker reports | the earnings release is the top story; surprise vs. expectations stated; peer read-through noted | 1 |
| word-ticker | ON over a busy week | only onsemi stories; no "turn on" / "on the" false matches | 1 |
| macro-day | a CPI or OPEC+ surprise, run for XOM | the macro/domain story outranks company noise; direction right for XOM | 3 |
| unexplained-move | a flagged move with no collected cause | searches the web, then gives a sourced cause or says "unexplained"; never invents one | 4 |
| dual-listing | TEVA on a day TASE moved while the US was closed | the TASE move is recorded; Hebrew items are handled | 4 |

Assertions are checked by script where possible:
- every story under "Top stories" cites at least one stored item id
- every date under "New dated events" appears in the text of the item it cites
- no tier-4 source reaches "Top stories" unless another source corroborates it
- the case's known main event ranks in the top 3

### 12.3 Trigger tuning (only if auto-invocation is turned on)

With `disable-model-invocation: true`, Claude never sees the description, so there's nothing to tune. If that's turned off (§15), write ~20 realistic prompts, about half of them should-trigger and half near-misses. You review the set, then the skill-creator optimizer tunes the description against it.

- **Should trigger:**
  - "why is onsemi down 8% this morning?"
  - "anything new on TEVA since Monday?"
  - "what catalysts are coming up for XOM this month?"
- **Shouldn't trigger:**
  - "plot NVDA's price for the last year" (graph plan)
  - "what's AAPL's P/E?"
  - "add MSFT to my watchlist"
  - "explain what an 8-K is"

### 12.4 Live quality ("golden week")

For one past week per test ticker, list what actually mattered (8-Ks, earnings, major headlines). Then measure:
- recall
- precision (the share of digest items you judge relevant)
- duplicate rate
- explained-move rate
- capture lag (first_seen − published)
- runtime and tokens per run

**Test tickers:**

| Ticker | Why it's in the set |
|---|---|
| NVDA | dense coverage, rich supply chain |
| ON | the ticker is a common word (disambiguation) |
| XOM | oil- and macro-driven |
| JPM | rates and regulation |
| TEVA | listed on both NYSE and TASE, with Hebrew coverage |
| one small biotech | an upcoming FDA decision |

## 13. Build phases

Each phase ends with something usable.

| Phase | Build | Done when |
|---|---|---|
| 0. Groundwork | Python 3.9 venv (in place), `pyproject.toml`, package skeleton, `.env`, `.gitignore` additions | `python -m investing.news --help` works; the test suite runs |
| 1. Company-level MVP | resolve; EDGAR, newsroom/newswire, Google News, Yahoo and Finnhub collectors (Finnhub also backfills a year of news); normalize, dedupe, sessions, store; SKILL.md + weighting.md; digest v1; profile v0 (identity + search terms); daily collection for the test tickers starts; first eval cases | `/asset-news NVDA` gives a digest whose top stories you agree with on 3 days in a row, and it contains every 8-K filed that week |
| 2. Profile + domain level | full profiles drafted by Claude; peer/supplier/customer events; domain ETFs; Federal Register; industry sources; GDELT; trend stories | a peer's or customer's material event shows up in NVDA's digest with the right link and direction |
| 3. Macro + calendar | shared daily macro pass: Fed, FRED release dates, BLS/BEA, Treasury, policy feeds, geopolitics, Polymarket/Kalshi; `events` filled from schedules and from dates in the news | the next 2 weeks of releases and the next earnings date are in `events`; one macro surprise reaches every affected ticker's digest from a single collection |
| 4. "Why?" + history | market/domain/own split; web search for unexplained moves; foreign-listing overnight moves; backfill (EDGAR full history, GDELT to 2017, Massive ~2 years, Finnhub 1 year); per-asset calibration; correlation check of profiles | for the last 20 flagged sessions per test ticker, most have a sourced explanation and the rest say "unexplained" |
| 5. Alternative data | positioning (13F, short interest); earnings-call transcripts; hiring; Bluesky; X pay-per-use for a short list of accounts if budget allows; NWS weather; shipping/flights/satellite only for profiles that need them | each source added improves the golden-week numbers (§12.4) or is dropped |
| 6. Daily automation | hourly collection-only runs 04:00–20:00 ET (no Claude) for accurate first-seen times; one Claude run per ticker per day after the shared pass (§13.1); alert when a collector fails 2 days running; cost caps | a week of unattended runs for the whole watchlist with no manual fixes |

### 13.1 Unattended runs (Phase 6)

```
claude -p "/asset-news NVDA" --permission-mode dontAsk --max-turns 60 --output-format json
```

- **Start in the project root.** Skills are found from the starting folder, so set Task Scheduler's "Start in" to the repo folder.
- **Pre-approve everything.** Unattended runs can't answer permission prompts, so anything not pre-approved is denied. The skill's `allowed-tools` must cover every command the run uses. If a test shows the frontmatter grant isn't enough, add `--allowedTools` with the same rules.
- **No `--bare`.** It skips skill discovery and needs an API key instead of your login.
- **Cap and log each run.** Use `--max-turns`, plus `--max-budget-usd` if usage is billed per call. `--output-format json` returns the result and a session id for the run log. Exit code 0 means success.
- **Local alternative:** Claude Desktop scheduled tasks run in a local folder, but only while the app is open and the PC is awake.
- **Cloud routines (`/schedule`, research preview) don't fit yet.** Each run starts from a fresh clone on Linux, so:
  - it can't see `data/` or the Windows `.venv`
  - results last only if they're committed and pushed
  - news sites would have to be added to the network allow-list

  That changes only if the database moves to a hosted service (§15).

## 14. Risks

| Risk | Mitigation |
|---|---|
| Terms of use, copyright | APIs and RSS first; obey robots.txt and rate limits; store snippets and links, not articles; re-check licensing before any public launch |
| Unofficial sources break or throttle (Google News RSS, Yahoo) | collectors isolated, so one failure doesn't stop the run; source-health report; fixture tests; a second source for each need (Finnhub backs up Yahoo and Google News). Google News links are opaque tokens, and decoding each one costs a throttled extra call, so dedupe those items by title + outlet and decode only the ones that reach `candidates.json` |
| Sources close or go paid (in 2025–26 alone: Bing, Reddit, StockTwits, Alpha Vantage news, the Truth Social tool) | no single source is essential; source-health report; re-check the source list every quarter |
| Ambiguous tickers (ON, ALL, NOW, T, F) | search names and aliases with exclude terms; Claude checks relevance |
| LLM mistakes (wrong date, invented fact) | cite item ids; quote the sentence behind each date or number; "unclear" is allowed |
| Bad timestamps | keep published_at and first_seen_at; normalize time zones; NYSE calendar for sessions and holidays |
| Look-ahead bias in backtests | append-only items; `--as-of` serves only what was seen by that date |
| SEO noise | credibility tiers, blocklist, novelty |
| Cost at 50 tickers | shared macro/domain pass, pre-filter, candidate cap; if needed, a cheaper model scores items in bulk while Claude keeps the digest and the "why" searches |

## 15. Open decisions

1. **Personal tool or public platform?** The free tiers checked (Yahoo, Finnhub, Massive, Tiingo) are for personal use only, with no redistribution, so a public platform needs paid data licenses. It also brings investment-advice rules. *Default: personal first.*
2. **Data budget:** free covers a lot: EDGAR, Google News, Yahoo, Finnhub and Massive free keys, GDELT, and the official calendars. The first paid item worth considering is X's pay-per-use API for a short list of accounts (CEOs, officials). At $0.005 per post read, 100 posts a day costs about $15 a month. *Default: free; decide after Phase 1's golden-week numbers.*
3. **Markets:** US-listed only, or other exchanges and non-English news too? *Default: US-listed, plus those stocks' foreign listings (Phase 4).*
4. **Where daily runs happen:** on this PC (Task Scheduler or Claude Desktop scheduled tasks; either way the PC must be on) or in the cloud? Cloud routines start from a fresh Linux clone each run and can't see local `data/`, so the cloud only works once the database is hosted (§13.1). *Default: this PC.*
5. **Skill name:** is `asset-news` OK?
6. **Auto-invocation:** should Claude start a run on its own when you ask about a stock, or only when you type `/asset-news`? *Default: only on `/asset-news`. Revisit once a read-only mode exists that answers from stored news without collecting.*

## 16. To verify

The first draft relied on knowledge that may be months old, so two checks ran on 2026-11-19. Both are done, and their results are folded into the plan. The open items below still need a hands-on test or a closer look.

### 16.1 Claude Code skill mechanics: done 2026-11-19

Checked against the Claude Code docs (skills, permissions, headless, CLI reference, routines) and the open Agent Skills spec. The results are folded into §10, §11, §12.3, §13.1 and §15.

What changed from the first draft:
- `allowed-tools` pre-approves; it doesn't restrict. It also matches commands literally, so the rule is now `PowerShell(.\.venv\Scripts\python.exe -m investing.news *)`, spelled exactly as the body runs it.
- `Write(…)` rules never match. `Edit(data/**)` covers writes.
- `disable-model-invocation: true` makes runs explicit, so trigger tuning only matters if it's turned off.
- `${CLAUDE_SKILL_DIR}`, `$0` / `$ARGUMENTS`, `shell: powershell` and `!` injection are all available.
- `claude -p "/asset-news …"` works from the project root.
- Cloud routines don't fit while the data lives on this PC.

To test by hand once the skill exists:
- [ ] Frontmatter accepts `PowerShell(…)` and `Edit(data/**)`, and the rule matches the exact commands Claude emits (`--verbose` shows them)
- [ ] `$0` gets substituted inside `!` commands
- [ ] Relative links inside the skill resolve (if not, use `${CLAUDE_SKILL_DIR}` everywhere)
- [ ] A full `claude -p` run started from Task Scheduler finishes with no permission stalls, and WebSearch and WebFetch work in it

### 16.2 Data sources: done 2026-11-19

All 28 sources were checked against official docs and pricing pages, with live test calls to SEC, Google News, GDELT and the Federal Register. The results are folded into §5, §8, §10.2, §13, §14 and §15.

What changed from the first draft:
- Reddit, StockTwits and Truth Social are out.
- Alpha Vantage news is now paid.
- Polygon.io is now Massive.
- Finnhub's free key (1 year of ticker-tagged news) joins Phase 1.
- Newswires have no per-company feeds.
- Google News links need a throttled decode step.
- BLS and BEA calendars are machine-readable.

Still open:
- [ ] FMP current prices; whether Tiingo's free key gets any news
- [ ] GDELT's official rate limit (~1 request per 5 s comes from community reports)
- [ ] Per-company feeds on GlobeNewswire / Business Wire
- [ ] Data-reuse terms for Polymarket, Kalshi and aisstream
- [ ] News history depth on Marketaux and on Massive's free key (confirm on first use)
- [ ] Reddit's shutdown dates and X's plan-migration dates come partly from third-party reports
