# Plan: `domain-scout` skill (domains and assets of interest, refreshed each period)

**Status:** draft 1, 2026-11-19 · the sources in §5 are being checked (§16)
**Requirements:** `thoughts_on_the_market.docx` ("Connect the dots") and the request of 2026-11-19
**Related plans:**
- `plan_scraper_of_data_sites.md`: `asset-news`, the deep dive per ticker
- `plan_graph_macro_domain_trend_in_markets.md`: risk-on/off regime
- `plan_report_creator.md`: daily report

---

## 1. Goal

`/domain-scout` runs once a period, weekly by default. Each run:
1. scans the web and the market for hot topics
2. compares them with the previous scan and with the current **pool** (the domains and tickers we follow)
3. flags domains that are emerging, strengthening, overheating or fading
4. maps the tickers in each candidate domain
5. builds a dossier for each ticker: fundamentals, analyst views, and the company's plans and milestones
6. proposes add / watch / remove changes to the pool, with reasons

You approve the changes. Approved tickers then go to `asset-news` (`/asset-news <TICKER> --refresh-profile`), which builds their profile and starts daily coverage.

In the doc's words this is:
- *"an analyst that scans the market for a pool of say 10–50 interesting companies (5–10 interesting domains to follow) – this list needs to be updated as some might be less interesting to the market"*
- *"a method of recommendations of which to add (domain/asset) and which to remove from that list"*
- *"recommendations of other stocks to open a position in, based on lower the risk and increase the revenue"*

**Not in this skill:**
- daily news per ticker: `asset-news`
- the regime graph: the graph plan
- position sizing and the cash "bank": a later plan
- trades

The output is research for you to decide on.

## 2. Design principles

1. **Attention is the hypothesis; money is the confirmation.** The doc puts information first, and says *"how they act is the confirmation"*. A domain counts as emerging when attention rises and money starts to confirm it.
   - Attention comes from news, filings, page views, new ETFs and prediction markets.
   - Money shows up as relative strength, breadth and volume.

   Attention without money is just talk. Money without attention gets a "why?" (§6).
2. **Trends take weeks.** The doc says macro moves like a big ship and big money moves in tranches. A domain needs several weeks of persistence before it's proposed, and the pool shouldn't churn. Patience over FOMO.
3. **A lifecycle, not just "hot".** Each domain gets a stage: emerging → confirmed → overheated → fading. *"Whatever moved a lot very fast"* is overheated. Per the doc it's volatile and likely to give some back, so it's watched, not added.
4. **Domains are the unit; tickers are the expression.** The doc says companies in the same domain move together. So the pool is built from domains that hedge each other (low correlation). Each domain is expressed through its ETF plus 1–3 tickers.
5. **Official numbers.** Fundamentals come from SEC XBRL filings. Analyst views and valuations come from market-data sources and are snapshotted weekly, which lets us measure revisions over time.
6. **Point-in-time.** Every signal is stored with the date it was known. `--as-of` can then replay past scans and test whether the scout would have spotted past themes early (§12).
7. **Shared code.** Prices, HTTP and storage are shared with `asset-news` in `src/investing/common/`.

## 3. One run, step by step

```
/domain-scout [--as-of DATE] [--deep "<domain>"] [--ticker TICKER]

1 load       assets/pool.yaml (current pool) + the previous scan
2 attention  theme signals: news volume, filing mentions, page views, prediction markets, new ETF filings
3 discover   Claude reads clusters of rising headlines and terms → candidate themes not tracked yet
4 money      per theme ETF and basket: relative strength vs SPY, breadth, volume, betas and ratios,
             correlation with the pool
5 stage      lifecycle stage per domain + change since the previous scan
6 map        candidate domains → tickers (ETF holdings, filing mentions, industry codes, peers),
             filtered for size and liquidity
7 dossier    per ticker: fundamentals, analyst view, valuation, volatility, plans and milestones
8 propose    add / watch / remove within the pool's limits → report data/scout/2026-11-19.md
9 hand-off   after your approval: update pool.yaml, run /asset-news <TICKER> --refresh-profile for new tickers
```

**Options:**
- `--deep "<domain>"` builds a full dossier for one domain on demand.
- `--ticker` checks one candidate ticker against its domain.
- `--as-of` replays a past date.

**Who does what:**
- CLI commands (`python -m investing.scout …`) handle the data parts of steps 2, 4 and 6, and the numbers in step 7.
- Claude handles discovery, judgment, the dossiers and the proposal.

## 4. The pool (`assets/pool.yaml`, in git)

```yaml
# illustrative
limits: {domains: [5, 10], tickers: [10, 50], tickers_per_domain: [1, 3]}
filters: {min_market_cap_usd: 1.0e9, min_avg_dollar_volume_usd: 2.0e7, listing: US}
domains:
  - name: semiconductors / AI accelerators
    status: pool                 # pool | watch | removed
    stage: confirmed             # from the last scan: emerging | confirmed | overheated | fading
    added: 2026-11-19
    thesis: "AI data-center build-out drives accelerator and memory demand"
    etfs: [SMH, SOXX]
    drivers: [hyperscaler capex, export controls, rates]
    review_by: 2027-02-19        # forced re-check date
    tickers:
      - {ticker: NVDA, status: pool, added: 2026-11-19, why: "domain leader; high purity"}
```

| Status | Meaning |
|---|---|
| `pool` | followed daily with `asset-news` |
| `watch` | a candidate, checked by each scan but without daily news |
| `removed` | kept for history |

Every change to the pool is a git commit whose message carries the scan's reasons, so the pool's history lives in git.

## 5. Signals and sources

### 5.1 Attention (the information)

| Signal | What it shows | Source | Phase |
|---|---|---|---|
| News volume per theme | share of global coverage; 4- and 12-week trend | GDELT timeline (free, back to 2017) · Google News RSS counts | 2 |
| Filing mentions | companies starting to discuss a theme in 10-K/10-Q/8-K (corporate adoption) | SEC EDGAR full-text search (free, 2001 onward) | 2 |
| Public interest | daily page views of the theme's Wikipedia articles | Wikimedia pageviews API (free) | 2 |
| Prediction markets | new or busier markets on the theme | Polymarket public search | 2 |
| New ETF filings | issuers file new thematic ETFs when they sense demand | EDGAR fund registration filings | 3 |
| Headline clusters | brand-new terms: a product, a technology, a policy | `asset-news` stories, GDELT and Google News headlines, clustered; Claude names the themes | 3 |
| Analyst attention | coverage initiations and rating changes across the theme | Yahoo up/downgrades; `asset-news` stories | 4 |

### 5.2 Money (the confirmation)

Money signals are computed from daily prices (Yahoo, with Massive's free end-of-day data as fallback). Each is calculated per theme ETF and per equal-weight basket of the theme's tickers.

| Signal | Definition | Phase |
|---|---|---|
| Relative strength | return vs SPY over 1, 3 and 6 months | 1 |
| Breadth | share of basket members above their 50-day average, and share with positive 3-month relative strength | 1 |
| Volume | dollar volume vs its 3-month average; volume on up days vs down days (the doc: big volume = money entering or leaving) | 1 |
| Volatility | beta vs SPY over 2 weeks, 1 month and 3 months, plus their ratios (doc); realized volatility; distance above the 50-day average | 1 |
| Correlation | 60-day and 1-year correlation with each domain already in the pool (the doc: domains that hedge each other) | 1 |
| ETF flows | change in shares outstanding × price | 3 |
| Institutional ownership | quarterly change in fund holdings from 13F (~45-day lag) | 4 |

### 5.3 Substance (per ticker)

| Data | Source | Phase |
|---|---|---|
| Fundamentals: revenue and growth, margins, free cash flow, cash, debt, share count (dilution) | SEC XBRL company facts: official and free; each value carries its filing date, so it's point-in-time | 4 |
| Valuation: P/E, EV/sales, EV/EBITDA | computed from XBRL plus prices; Yahoo as a cross-check | 4 |
| Analyst view: consensus rating, number of analysts, target vs price, estimate revisions | Yahoo (`yfinance`) and Finnhub free endpoints, snapshotted weekly to build our own revisions history | 4 |
| Plans and milestones: guidance, product and capacity timelines, approvals, investor-day targets | latest 10-K/10-Q, 8-K earnings releases (exhibit 99.1), investor presentations. Claude extracts dated milestones → calendar | 4 |
| Theme membership and purity | ETF holdings (issuer files; SEC N-PORT as the official fallback), filing mentions, industry codes (SEC SIC, Yahoo industry), 10-K segment revenue | 4 |
| Red flags | going-concern language, 8-K item 4.02 restatements, heavy dilution, short cash runway | EDGAR | 4 |

## 6. Lifecycle stages

Each domain gets three scores (0–100). Each score is built from standardized signals, compared both with the domain's own history and with other domains:

| Score | Built from |
|---|---|
| Attention | level and 4/12-week change in news volume, filing mentions, page views, prediction markets |
| Money | relative strength, breadth, volume, flows |
| Heat | how stretched it is: distance above trend, short-term beta far above long-term, speed of the move, media saturation |

Stage rules. The thresholds are starting points, tuned by the backtest in Phase 6.

| Stage | Pattern | Default action |
|---|---|---|
| emerging | attention rising for ≥ 3 weeks; money turning up (relative strength improving, breadth > 40%); heat moderate | add to **watch**; build a dossier |
| confirmed | attention high and persistent; relative strength positive over 3 and 6 months; breadth > 60% | eligible for the **pool** |
| overheated | high heat: a parabolic move, short-term beta far above long-term, media saturation | don't add. Wait for a pullback (the doc: what rose fast falls fast; patience) |
| fading | attention falling, relative strength negative, breadth falling, heavier volume on down days | **remove** candidate after 2 fading scans in a row |
| quiet | neither attention nor money | ignore |

**Mismatches get a "why?":**
- When money moves without attention, Claude looks for the cause, such as a policy change the news hasn't caught up with.
- When attention rises without money, it's labeled hype until buyers show up.

## 7. From domain to tickers

### 7.1 Mapping

Collect candidates from all four sources, then filter:
1. holdings of the theme's ETFs
2. companies whose filings mention the theme, weighted by how central it is (the Business section counts more than a passing mention)
3. industry codes and peer lists
4. Claude's research for names the above miss, such as recent IPOs

Default filters: US listing, market cap ≥ $1B, average daily dollar volume ≥ $20M. Institutions need liquidity, and hot themes attract low-quality microcaps.

### 7.2 Ranking within a domain (to pick 1–3)

| Criterion | What it measures |
|---|---|
| Purity | share of revenue from the theme (10-K segments) |
| Leadership | relative strength within the domain |
| Quality | revenue growth and whether it's accelerating, gross margin, free cash flow, balance sheet, dilution |
| Valuation | vs the domain median and vs growth |
| Analysts | rating, target upside, direction of revisions (revisions say more than levels) |
| Risk/reward | upside (analyst target, growth) against risk (betas, drawdowns, red flags): the doc's "lower the risk and increase the revenue" |
| Volatility | betas and their ratios; a flag for "moved a lot very fast" |
| Plans | credible, dated milestones within the next 1–4 quarters (the doc: timing matters, not too early and not too late) |

### 7.3 Dossier per ticker

```
## NVDA: semiconductors / AI accelerators (purity: high)
Thesis         one line · the domain's stage · why now
Fundamentals   revenue, growth (y/y; accelerating?), gross margin, FCF, net cash, share count trend
Valuation      P/E, EV/sales vs domain median and vs growth
Analysts       consensus, # analysts, target vs price, revisions (30 / 90 days)
Volatility     beta 2w / 1m / 3m and ratios; distance above 50-day average
Plans          guidance and dated milestones → calendar
Risks          red flags, customer concentration, regulation
Hand-off       /asset-news NVDA --refresh-profile
```

## 8. Recommendation rules

Proposals must follow these rules:

| Rule | Detail |
|---|---|
| Pool limits | 5–10 domains, 10–50 tickers, 1–3 per domain (from the doc) |
| Diversification | a new domain must add something: correlation below ~0.6 with the domains already in the pool, or a hedge (negative correlation) |
| Regime fit | once the graph plan exists: in risk-off periods, favor low-beta domains and avoid volatile ones (doc) |
| Persistence | nothing is added or removed on a single scan. New domains go to watch first; removal takes 2 fading scans |
| Churn cap | at most ~2 domain changes a month, so the pool stays stable |
| Evidence | every proposal cites its signals and sources, and says what would change the call |

**Each scan's report contains:**
- the proposals table: action, object, stage, scores, reasons, evidence
- dossiers for new candidates
- a health check of the current pool

Nothing in `pool.yaml` changes without your approval. Edits to it are deliberately left out of `allowed-tools`, so Claude has to ask.

## 9. Storage

```
assets/pool.yaml            current pool (in git; history = commits)
assets/themes.yaml          tracked themes: names, search terms, ETFs, parent theme (in git)
data/scout.db               SQLite: theme_signals (weekly, point-in-time), theme_members,
                            fundamentals, analyst_snapshots, scans, proposals, your verdicts
data/scout/<YYYY-MM-DD>.md  scan reports
```

Themes are hierarchical, e.g. AI → AI chips, AI power, AI software, because a broad theme like "AI" is too vague to measure. Every theme needs at least one ETF or a basket so its money signals can be computed.

`themes.yaml` starts with about 40 themes and their ETFs. Examples:

| Theme | ETF |
|---|---|
| Semiconductors | SMH |
| Cybersecurity | CIBR |
| Uranium | URA |
| Defense | ITA |
| Robotics | BOTZ |
| Biotech | XBI |
| Regional banks | KRE |
| Homebuilders | ITB |
| Oil & gas | XLE |
| Gold miners | GDX |
| Copper miners | COPX |
| Rare earths | REMX |

The 11 S&P sector ETFs are included for context. Discovery (step 3) adds new themes once you approve them.

## 10. Skill package and code

```
.claude/skills/domain-scout/
  SKILL.md
  references/
    signals.md            each signal: definition, source, query pattern, limits
    lifecycle.md          stage rules and thresholds, with worked examples
    dossier-rubric.md     judging fundamentals, analysts, valuation, plans
    report-template.md
  evals/
src/investing/scout/
  cli.py                  attention | money | stage | map | fundamentals | analysts | report-data | apply-pool
  attention/              gdelt.py  edgar_fts.py  wikipedia.py  polymarket.py  etf_filings.py
  money.py                relative strength, breadth, volume, betas, correlations
  mapping.py              ETF holdings, filing mentions, industry codes, purity
  fundamentals.py         SEC XBRL company facts → metrics, point-in-time
  analysts.py             weekly snapshots → revisions
src/investing/common/     http, prices, storage (shared with investing.news)
```

The frontmatter follows the same conventions as `asset-news`, which were checked on 2026-11-19 (plan_scraper §10):

```yaml
---
name: domain-scout
description: Scans the web and the market for emerging, strengthening, overheated and fading domains, maps their tickers with fundamentals, analyst views and business plans, and proposes changes to the followed pool.
argument-hint: "[--as-of DATE] [--deep \"<domain>\"] [--ticker TICKER]"
disable-model-invocation: true
shell: powershell
allowed-tools: PowerShell(.\.venv\Scripts\python.exe -m investing.scout *), WebSearch, WebFetch, Edit(data/**)
---
```

`assets/pool.yaml` and `assets/themes.yaml` are deliberately left out of `allowed-tools`, so changing them always asks you.

## 11. How we build it

It's the same skill-creator loop as `asset-news` (plan_scraper §11):
1. code with tests
2. SKILL.md and references
3. eval cases
4. runs with and without the skill
5. your review in the viewer
6. improve, then repeat

## 12. Testing and evaluation

### 12.1 Backtest the detector

Replay past dates with `--as-of` and check whether the scout flagged known themes early, before the big move:
- GLP-1 / obesity drugs (2023)
- data-center power and nuclear (2024)
- quantum computing (late 2024)

Measure:
- **Lead time:** weeks from the first "emerging" flag to the domain's breakout
- **Hit rate:** flags that became "confirmed"
- **False positives**
- **Churn:** monthly pool churn

Avoid three look-ahead traps:
- **Today's ETF holdings** didn't exist back then. Use filing mentions and N-PORT holdings as of the date.
- **Restated fundamentals.** Use XBRL values by filing date.
- **Survivorship.** Delisted companies are missing from current lists, so keep them in the store.

### 12.2 Skill evals on frozen data

| Case | Situation | A good result |
|---|---|---|
| new-domain | a theme crosses into "emerging" | proposed for watch, with a dossier, evidence and a correlation/hedge note |
| overheated | a theme that went parabolic | flagged overheated and not added, with the reason for waiting |
| fading-exit | a pool domain fading for 2 scans | a remove proposal with evidence |
| stable-week | nothing meaningful changes | no churn; a short report |
| bad-ticker | a hot-theme microcap with dilution and going-concern language | filtered out or red-flagged |

Assertions are checked by script where possible:
- every proposal cites signals and sources
- fundamentals match the SEC XBRL values
- pool limits are respected
- nothing is added or removed on a single scan
- no ticker is below the size and liquidity filters

### 12.3 Your verdicts

Each scan stores your verdict on every proposal: agree or disagree, and why. That's the best data for tuning the thresholds.

## 13. Build phases

| Phase | Build | Done when |
|---|---|---|
| 0. Groundwork | shared with `asset-news` Phase 0, plus `src/investing/common/` (prices, http, storage) | prices for SPY and the seed ETFs load into the store |
| 1. Money map | `themes.yaml` seed; money signals per theme ETF; `pool.yaml` schema; report v0: domains ranked by money signals, with changes since last week | the weekly table of rising and fading domains looks sensible to you |
| 2. Attention + stages | GDELT timelines, EDGAR mention counts, Wikipedia page views, Polymarket; attention score; lifecycle stages; diff vs the previous scan | every seed theme has a stage, and at least one "money without attention" case is explained |
| 3. Discovery | headline clustering → candidate themes; new ETF filings; ETF flows; new themes added to `themes.yaml` with your approval | a theme not in the seed list is found and measured |
| 4. Tickers + dossiers | mapping and purity; size and liquidity filters; XBRL fundamentals; analyst snapshots; plans and milestones; red flags; 13F changes | dossiers for 3 domains whose numbers match the SEC filings |
| 5. Proposals + hand-off | recommendation rules; approval flow; `pool.yaml` commits; `/asset-news --refresh-profile` for new tickers | one full weekly cycle: scan → proposals → your approval → new profiles → daily news |
| 6. Backtest + automation | point-in-time replays (§12.1); threshold tuning; weekly unattended run, set up like asset-news (plan_scraper §13.1) but with proposals waiting for your approval | the backtest flags at least 2 of the 3 historical themes before their breakout, with a false-positive rate you accept |

## 14. Risks

| Risk | Mitigation |
|---|---|
| Chasing hype (FOMO) | lifecycle stages, persistence rules, overheated flag, churn cap |
| Look-ahead bias in backtests | point-in-time signals; XBRL by filing date; N-PORT holdings as of the date |
| Survivorship bias | keep delisted tickers in the store |
| Vague themes ("AI") | hierarchical themes, each with an ETF or basket |
| Low-quality small caps in hot themes | size and liquidity filters; dilution, going-concern and restatement flags |
| Unofficial data breaks (Yahoo) | SEC XBRL for fundamentals; Finnhub as a fallback for analyst data |
| Thin free analyst data | weekly snapshots build our own revisions history |
| Recommendations read as advice | it's a personal research tool and you decide; see plan_scraper §15.1 on public use |

## 15. Open decisions

1. **Pool limits:** 5–10 domains, 10–50 tickers, 1–3 tickers per domain, as in the doc?
2. **Filters:** US-listed, market cap ≥ $1B, ≥ $20M traded per day?
3. **Cadence:** a weekly scan plus a monthly deep review? On which weekday?
4. **Tiers:** should candidates sit in `watch` (checked each scan) before joining the `pool` (daily `asset-news`)?
5. **Skill name:** is `domain-scout` OK?
6. **Starting pool:** do you already follow some domains or tickers? They would seed `pool.yaml`.

## 16. To verify

A check of these sources started on 2026-11-19. Tick each item as it's confirmed or corrected, and fix the section it affects.

- [ ] SEC XBRL APIs (company facts, frames): filing dates for point-in-time values; limits
- [ ] EDGAR full-text search: phrase, form and date filters; hit counts per period
- [ ] Wikimedia pageviews API
- [ ] GDELT timeline modes (coverage volume over time): lookback, limits
- [ ] Google Trends: access to the official API; pytrends status
- [ ] `yfinance` analyst and classification data (estimates, revisions, targets, sector/industry lists)
- [ ] Finnhub free endpoints: recommendation trends, peers, profile, basic financials, price targets
- [ ] ETF holdings files (iShares, SPDR, Global X, VanEck, ARK) and SEC N-PORT
- [ ] Free ETF shares-outstanding / flow data
- [ ] New ETF filings on EDGAR (form types)
- [ ] Massive free tier: ticker details (SIC), related companies
- [ ] Hacker News and arXiv APIs as tech-attention signals
