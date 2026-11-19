# Plan: `domain-scout` skill (domains and assets of interest, refreshed each period)

**Status:** draft 2, 2026-11-19
- the pool (§4) is agreed
- collection (Part A, §5) is redesigned to be deterministic and free
- VCs, visionaries and forecasters are general sources that feed a monthly radar: hot now, hot later, cooling (§5.6, §5.13)
- analysis (Part B, §6–8) is to be reviewed later

**Requirements:** `thoughts_on_the_market.docx` ("Connect the dots") and the requests of 2026-11-19
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

Once a month it also publishes a **radar**: a general list of themes that are hot now, hot later (1–5 years) or cooling. It's built from VCs, visionaries and forecasters who aren't tied to any one domain (§5.6, §5.13). The radar is how new domains come onto our screen, and how we lose interest in others.

The plan has two parts:

| Part | Sections | Status |
|---|---|---|
| A. Collection | §5 | deterministic and free |
| B. Analysis | §6–8 | a first draft, reviewed later |

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

1. **Deterministic, free collection.**
   - Fetching is plain code: no LLM in the loop, and no paid sites or tools.
   - The LLM's job in collection is to choose each domain's sources and write their fetcher specs (§5).
   - Reading the fetched content belongs to the analysis part.
2. **Each domain has its own sources.** Like a ticker's profile in `asset-news`, each domain gets its own source map. Biotech needs clinical-trial data; power needs grid data; semis need trade data. VCs, visionaries and forecasters are the exception: they're general sources that look across all domains (§5.6).
3. **Attention is the hypothesis; money is the confirmation.** The doc puts information first, and says *"how they act is the confirmation"*. A domain counts as emerging when attention rises and money starts to confirm it.
   - Attention comes from news, analysts, visionaries, VC activity, filings, research and page views.
   - Money shows up as relative strength, breadth and volume.

   Attention without money is just talk. Money without attention gets a "why?" (§6).
4. **Trends take weeks.** The doc says macro moves like a big ship and big money moves in tranches. A domain needs several weeks of persistence before it's proposed, and the pool shouldn't churn. Patience over FOMO.
5. **A lifecycle, not just "hot".** Each domain gets a stage: emerging → confirmed → overheated → fading. *"Whatever moved a lot very fast"* is overheated. Per the doc it's volatile and likely to give some back, so it's watched, not added.
6. **Domains are the unit; tickers are the expression.** The doc says companies in the same domain move together. So the pool is built from domains that hedge each other (low correlation). Each domain is expressed through its ETF plus 1–3 tickers.
7. **Point-in-time.** Every document and number is stored with the time it was first seen. `--as-of` can then replay past scans and test whether the scout would have spotted past themes early (§12).
8. **One engine for both skills.** The fetcher engine (`src/investing/fetch/`), prices and storage are shared with `asset-news`. Its collectors can move onto the same specs later.

## 3. Modes and one scan, step by step

```
python -m investing.fetch run --due                                       collection on a timer, no LLM (Part A)
/domain-scout --sources "<domain>"                                        build or refresh a domain's source map (§5.1)
/domain-scout --sources horizon                                           build or refresh the general horizon sources (§5.6)
/domain-scout --repair                                                    fix fetchers marked broken (§5.8)
/domain-scout --radar                                                     monthly list: hot now / hot later / cooling (§5.13)
/domain-scout [--as-of DATE] [--deep "<domain>"] [--ticker TICKER]        weekly scan (Part B)
```

The weekly scan:

```
1 load       assets/pool.yaml (current pool) + the previous scan
2 attention  this period's documents and metrics, already collected by the fetchers
3 discover   Claude reviews only the flagged emerging terms (§5.7) → candidate themes not tracked yet
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

| Who | Does |
|---|---|
| Fetcher engine (`python -m investing.fetch`) | collects everything on a timer, with no LLM (§5) |
| Scout CLI (`python -m investing.scout …`) | money signals, ticker mapping, the numbers in the dossiers |
| Claude, design time | source maps and repairs |
| Claude, analysis | discovery, judgment, dossiers, proposals |

## 4. The pool (`assets/pool.yaml`, in git; agreed 2026-11-19)

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
    sources: assets/sources/semiconductors/   # the domain's source map (§5)
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

## 5. Part A: sources and fetchers (deterministic, free)

**Rules for collection:**
- No paid websites, APIs or tools. No logins, paywalls or headless browsers.
- No LLM in the fetch loop. Fetching, parsing, de-duplication, tagging and counting are plain code. The same input always gives the same output, and a run costs nothing but bandwidth.
- The LLM works at design time only: it chooses each domain's sources and writes their fetcher specs. Reading what was fetched belongs to the analysis part.

### 5.1 How it works

```
DESIGN TIME (LLM, rare)                                   RUN TIME (plain code, daily / weekly)
/domain-scout --sources "<domain>"                        python -m investing.fetch run --due
 1 fill in the domain's coverage checklist (5.4)           1 pick the fetchers that are due
 2 find candidate sources: web search + snowball (5.5)     2 fetch with conditional requests, politely (5.8)
 3 write a fetcher spec per source (5.3)                   3 parse with the spec → documents or metrics
 4 validate each spec: fetch twice, robots.txt,            4 normalize, de-duplicate, tag, count (5.7)
   parse checks, rate limit, terms note                    5 store with first-seen time; record health
 5 you review and approve the domain's source map          6 flag broken fetchers for repair (5.8)
                    │                                                     ▲
                    └──── specs in assets/sources/<domain>/*.yaml ────────┘
```

The LLM is called only in three cases, each with a token budget:
- a domain is added (`--sources`)
- a fetcher breaks (`--repair`)
- the quarterly source review, which works from the engine's yield and reach statistics

### 5.2 Fetcher types

Fetchers are declarative specs, run by one fixed engine: the LLM writes YAML, not code. In order of preference:

| Type | For | Example |
|---|---|---|
| `rss` | blogs and newsletters (Substack, Medium, WordPress), news sites, YouTube channels, podcasts, regulators | a Substack's `/feed` |
| `json_api` | free public APIs, keyless or with a free key | EDGAR full-text search, GitHub search, Hacker News, OpenAlex |
| `bulk_file` | CSV / XLSX / ZIP files published on a schedule | SEC Form D data sets, ETF holdings, grid interconnection queues |
| `sitemap` | news sites without RSS | a site's news sitemap |
| `html_list` | listing pages without a feed; CSS selectors for title, link and date | a VC firm's "perspectives" page |
| `diff_page` | pages that matter when they change | YC's Requests for Startups, a regulator's guidance page |
| `plugin` | logic a spec can't express: a small Python module with a fixed interface and a saved-response test | only after your review |

### 5.3 Fetcher specs

A **document** fetcher produces text that the analysis part reads later:

```yaml
id: semis.example-analyst            # illustrative
domains: [semiconductors]
category: analyst_blog               # one of the checklist categories (5.4)
why: "widely cited semis supply-chain analysis; often early on capacity and pricing"
type: rss
url: https://example-analyst.substack.com/feed
schedule: daily
output: documents
fields: {title: title, url: link, published: published, author: author, summary: summary}
full_text: when_free                 # extract article text only when it's freely readable
terms: {robots_ok: true, note: "free posts only; paid posts arrive as teasers"}
status: candidate                    # candidate → active → broken → retired
created_by: llm                      # llm | you
validated: 2026-11-19
version: 1
```

A **metric** fetcher produces numbers, so nothing needs reading:

```yaml
id: ai.github-new-llm-repos
domains: [ai-software]
category: developer_activity
why: "new open-source projects on a topic come before commercial adoption"
type: json_api
url: https://api.github.com/search/repositories
params: {q: "topic:llm created:{week_start}..{week_end}", per_page: 1}
schedule: weekly
output: metrics
metric: {name: github_new_repos_llm, value: "$.total_count"}
```

Every stored document and number carries its spec's id and version, so it can be traced back to how it was fetched.

### 5.4 Coverage checklist per domain

Every domain's source map covers each category that applies to it. The LLM fills in the checklist, the validator checks it, and every source states `why` it's there.

VCs, visionaries, forecasters and general government R&D money aren't in this checklist, because they're general sources (5.6). Domain-specific public money, such as DoD contracts for defense or NIH grants for biotech, counts as official domain data.

| Category | Question it answers | Free, deterministic sources (examples) |
|---|---|---|
| Analyst blogs and newsletters | what widely read analysts think (5.5) | Substack, Medium, personal blogs, YouTube channels, podcasts, all via RSS |
| Innovation news | new technologies and products | the domain's trade press and science/tech outlets, via RSS or sitemaps |
| Trading and market news | how the market reads the domain | market-news outlets' RSS · Google News RSS per theme |
| Official domain data | the domain's hard numbers | **semis:** industry monthly sales; Korea's 10-day exports come only as Korean-language press releases, so they're manual for now · **power:** EIA generator inventory (free key); grid interconnection queues (CAISO downloads freely; other operators block scripts, so Berkeley Lab's yearly "Queued Up" file is the fallback) · **biotech:** ClinicalTrials.gov, openFDA, NIH grants · **defense:** DoD contract headlines (the war.gov feed; the detail pages block scripts) · **space:** Launch Library 2 (15 requests/hour) · **crypto:** DefiLlama (free, no key) |
| Research and developer activity | tech themes, often 1–3 years ahead of revenue | arXiv · OpenAlex (a free daily budget per IP; a free key raises it) · bioRxiv (its DOIs moved to prefix 10.64898 in Dec 2025) · Semantic Scholar (free key) · GitHub new repos per topic (free token) · PyPI downloads (180 days) and npm downloads (18 months per call) · Hugging Face models per task |
| Patents | long-horizon commitments | none for now: PatentsView shut down in 2026, and the USPTO's replacement needs an identity-verified account (5.12) |
| Hiring | where companies are putting people | public job boards (Greenhouse, Lever, Ashby) · H-1B filings by employer and job title (DOL, quarterly files) · Hacker News "Who is hiring" mentions |
| Policy and regulation | rules that open or close a market | Federal Register by agency · regulations.gov dockets and comment counts (free key) · congress.gov bills by subject |
| Attention | how much the world talks about it | the cross-domain metrics in 5.9 |

The source examples in this table are being checked (§16.2).

### 5.5 Finding widely read analysts and visionaries without paid tools

**Discovery.** The LLM proposes candidates for each domain. It searches the web for "best newsletters/blogs on <domain>" lists and looks at who other analysts cite. Visionaries and VCs go through the same discovery and reach score, but as general sources (5.6). Two mechanical sources add candidates cheaply:
- **Snowball:** each week the engine counts which outside sites our active sources link to most, and the top new sites become candidates.
- **Curated lists:** Substack publications' "recommended" lists, and topic lists on GitHub ("awesome-…").

**Reach score.** The engine computes it and refreshes it monthly:

| Part | Measured by |
|---|---|
| Audience (where public) | Substack subscriber counts (rounded, from its unofficial JSON, which also lists who recommends whom) · YouTube subscriber counts (free API key, 10,000 units/day) · podcast chart positions (Apple's free chart feeds) · the site's rank in the free Tranco top-sites list |
| Influence | how often Hacker News links to the site (Algolia search by URL) · how often our other sources link to it or quote it (a citation count inside our own collection) |
| Activity | posts per month, read from the feed |
| Originality | the share of its stories that we saw there first, before other sources |

The top sources per domain stay active. Feeds that go quiet or lose reach are retired automatically. Track record (did a source's calls come before the moves?) belongs to the analysis part. For visionaries, that means scoring their dated predictions once the dates pass (5.6).

### 5.6 The horizon layer: VCs, visionaries, forecasters and governments (general, not per domain)

These sources aren't tied to any domain. Their job is to open our eyes to new domains, and to tell us when to lose interest in others.
- They live in `assets/sources/horizon/` and are set up with `/domain-scout --sources horizon`.
- They feed the monthly radar (5.13).
- Everything they publish is matched against every theme in `themes.yaml`. Terms that match no theme go to the emerging-term check (5.7, step 6) as candidates for new themes.

| Layer | Sources | Deterministic signal |
|---|---|---|
| What visionaries predict | visionaries' and futurists' blogs, newsletters, podcasts and talk titles. Podcast transcripts are rare (about 5% of episodes), so they're a bonus · annual trend reports and breakthrough lists. MIT Technology Review, Deloitte, McKinsey, the Stanford AI Index and State of AI are free. ARK Big Ideas sits behind an email form. WEF, McKinsey and Gartner block scripts, so those are downloaded by hand once a year · Epoch AI's data on AI compute and models (CC BY) | theme-term counts per quarter · **convergence**: how many independent visionaries and reports name a theme in the same year · the year a theme first appears on the lists |
| What forecasting crowds expect | long-dated questions on technology milestones on Manifold (free, no login; Metaculus now needs one) · long-dated Polymarket and Kalshi markets | forecast probability or expected date, tracked over time; the shifts are the signal |
| What VCs say | firm blogs and annual outlooks: RSS where offered (e.g. a16z, now on Substack); Bessemer, NFX and First Round only have sitemaps · partner newsletters · YC's Requests for Startups page (diffed) | theme-term counts per year, matched against `themes.yaml` · YC page diffs |
| What VCs and founders do | SEC Form D: each filing's XML and the quarterly data sets carry industry group, amount and fund type ("Venture Capital Fund"). The data-set address changed in 2026 · funding-round news from the TechCrunch and Crunchbase News feeds, with round size and stage parsed from headlines by pattern ("raises $40M Series B") · YC batch mix from the community yc-oss JSON (YC has no official feed) | dollars and deal counts per theme per quarter · each tag's share of a YC batch |
| What governments fund | SBIR/STTR (its API is down, so the monthly bulk file instead; no awards Oct 2025–Apr 2026 while the program lapsed) · NSF and NIH award APIs · USAspending · DOE and CHIPS announcements · DoD contract headlines | award dollars per theme per quarter |

These are slow signals, measured in quarters and years. They mark domains early and set the 5-year context, but they say nothing about timing. In hard tech (energy, defense, space, biotech, semis), public money often leads private money.

**Optimists and skeptics.** The horizon sources include well-known skeptics next to the visionaries, so the analysis sees both sides (the doc: no FOMO).

**Track record.** Visionaries give the longest lead time and the lowest precision, and hype is common in this layer. Their content is stored with first-seen dates. Once the target dates pass, the analysis part can pull out their dated predictions and score who called it right. That score decides how much weight each visionary gets.

### 5.7 Deterministic processing before any LLM reads anything

Everything here is code, so the analysis part's LLM costs stay low:
1. **Normalize:** UTF-8 text, dates in UTC, canonical URLs.
2. **De-duplicate:** by URL, content hash and near-identical titles.
3. **Extract text:** the main text where the terms allow (trafilatura), plus language detection.
4. **Tag:** dictionary matches for tickers and company names (from the pool and the profiles) and theme terms (from `themes.yaml`).
5. **Count:** mentions per theme per week, split by category (VC, analysts, innovation news, trading news), next to the metric fetchers' numbers.
6. **Flag emerging terms without an LLM:** count n-grams in all titles each week. Flag terms that jump well above their 12-week baseline and appear in several independent sources. Only this short list goes to the LLM, for naming and judgment.
7. **Package for analysis:** cleaned text, metadata, tags, cluster id and first-seen time, capped per domain per run.

### 5.8 Politeness, health and repair

**Politeness:**
- obey robots.txt
- at most 1 request per second per host by default, or the source's published limit if it's lower
- conditional requests (ETag, If-Modified-Since)
- a User-Agent with your contact email
- back off on 429 errors

**Health:** each run records, per fetcher, the status, items found, new items, parse failures and latency. A fetcher is marked `broken` after 3 failures in a row, or after zero items for twice its usual gap.

**Repair** (`/domain-scout --repair`): the LLM gets the spec and the last good raw response, and proposes a fix, such as a new URL or new selectors. The fix goes through the validator before it goes live. Raw responses are kept for exactly this reason.

### 5.9 Cross-domain attention metrics (same for every domain)

| Signal | What it shows | Source | Phase |
|---|---|---|---|
| News volume per theme | share of global coverage; 4- and 12-week trend | GDELT timeline modes: free, back to 2017, 1 request per 5 s. **Degraded in Nov 2026** (missing days, low totals), so a data-quality check runs first, with Google News RSS counts as the backup | 1 |
| Filing mentions | companies starting to discuss a theme in 10-K/10-Q/8-K (corporate adoption) | SEC EDGAR full-text search: free, 2001 onward; phrase, form and date filters; exact counts per period from its form aggregation. It counts documents (each exhibit separately), not filings, and the API is undocumented | 1 |
| Public interest | daily page views of the theme's Wikipedia articles | Wikimedia pageviews API: free, daily since July 2015; needs a `name/version (contact)` User-Agent; 200 requests/min | 1 |
| Tech attention | developer and research activity on tech themes, often ahead of products | Hacker News (Algolia API) and arXiv API: free; counts per period (arXiv allows 1 request per 3 s) | 1 |
| Prediction markets | new or busier markets on the theme | Polymarket public search | 1 |
| New ETF filings | issuers file new thematic ETFs when they sense demand | EDGAR forms: 485APOS (a new fund series, effective ~75 days later) and 8-A12B (exchange registration, close to listing); S-1 for commodity and crypto trusts | 1 |
| Emerging terms | brand-new terms: a product, a technology, a policy | n-gram bursts over all fetched titles (5.7); the LLM only names the flagged terms | 3 |
| Analyst attention | coverage initiations and rating changes across the theme | Yahoo up/downgrades; `asset-news` stories | 5 |

### 5.10 Market data: money signals (the confirmation)

Money signals are computed from daily prices: Yahoo, with Massive's free end-of-day data as the fallback. Each one is calculated per theme ETF and per equal-weight basket of the theme's tickers.

| Signal | Definition | Phase |
|---|---|---|
| Relative strength | return vs SPY over 1, 3 and 6 months | 2 |
| Breadth | share of basket members above their 50-day average, and share with positive 3-month relative strength | 2 |
| Volume | dollar volume vs its 3-month average; volume on up days vs down days (the doc: big volume = money entering or leaving) | 2 |
| Volatility | beta vs SPY over 2 weeks, 1 month and 3 months, plus their ratios (doc); realized volatility; distance above the 50-day average | 2 |
| Correlation | 60-day and 1-year correlation with each domain already in the pool (the doc: domains that hedge each other) | 2 |
| ETF flows | change in shares outstanding × NAV. No free API exists, so we snapshot issuer files daily: shares outstanding is in the iShares CSV header, and SPDR's NAV history file goes back years. N-PORT monthly flows serve as a lagged cross-check | 4 |
| Institutional ownership | quarterly change in fund holdings from 13F (~45-day lag) | 4 |

### 5.11 Company data (per ticker)

| Data | Source | Phase |
|---|---|---|
| Fundamentals: revenue and growth, margins, free cash flow, cash, debt, share count (dilution) | SEC XBRL company facts: official, free, 2009 onward. Every value carries its filing date (`filed`), so point-in-time means keeping facts filed on or before the date. The frames API keeps only the latest filing, so it isn't point-in-time. Whole-company facts only, with no segments | 5 |
| Valuation: P/E, EV/sales, EV/EBITDA | computed from XBRL plus prices; Yahoo as a cross-check | 5 |
| Analyst view: consensus rating, number of analysts, target vs price, estimate revisions | Yahoo (`yfinance`): consensus, targets, estimates and their 7–90-day trend, up/downgrades. Finnhub free tier: recommendation trends, the last 4 earnings surprises (its targets and estimates are premium). Snapshotted weekly to build our own revisions history | 5 |
| Plans and milestones: guidance, product and capacity timelines, approvals, investor-day targets | latest 10-K/10-Q, 8-K earnings releases (exhibit 99.1), investor presentations; Claude extracts dated milestones → calendar | 5 |
| Theme membership and purity | ETF holdings files from iShares, SPDR, Global X, VanEck and ARK (free, latest day only) · SEC N-PORT as the official point-in-time fallback (quarterly, ~60-day delay) · filing mentions · industry codes (SEC SIC; Yahoo sector/industry lists with top companies) · Massive's related-companies endpoint (free key). Segment revenue isn't in the XBRL API, so Claude reads the segment note in the 10-K | 5 |
| Red flags | going-concern language, 8-K item 4.02 restatements, heavy dilution, short cash runway | EDGAR | 5 |

### 5.12 Not used, and why (checked 2026-11-19)

| Source | Why not |
|---|---|
| Paid data tools (Crunchbase, PitchBook, CB Insights, Similarweb and the like) | not free. Form D, YC, funding-round news and Tranco answer the same questions more roughly, for free |
| Logins, paywalls, headless browsers | fragile, and often against site terms |
| YouTube transcripts | YouTube's terms don't allow automated downloads, and its API gives captions only to a video's owner. We keep titles and descriptions from the channel feed, and use podcast transcripts where the publisher includes them |
| Google Trends | the official API is an apply-only alpha, and the unofficial pytrends is archived. Worth applying for alpha access later |
| USPTO patent data (PatentsView's replacement) | needs an identity-verified account, which breaks the no-login rule |
| Metaculus | its API now needs an account token |
| Korea Customs 10-day exports API | there isn't one; the figures come only as Korean-language press releases |
| FTSG Tech Trends Report | discontinued; its 2026 replacement forbids AI use, and sharing it needs approval |
| X (Twitter) | pay-per-use only (plan_scraper §15.2) |
| Finnhub price targets, estimates, ETF endpoints | premium only; Yahoo covers targets and estimates |
| Reselling or republishing ETF holdings files | personal analysis only; SPDR's file forbids reproduction without consent |

### 5.13 Hot now vs. hot later: the monthly radar

The radar is a general list of themes, not tied to the pool. It's refreshed monthly, because the horizon signals move slowly. It weighs two kinds of evidence:

| Evidence | Question | From |
|---|---|---|
| Future | are money and attention lining up for later? | the horizon layer (5.6): VC words and deals, visionary convergence, forecasting crowds, government R&D money; plus research and developer activity (5.4) |
| Present | is the market paying for it now? | money signals (5.10), trading news, attention metrics (5.9) |

| List | First-pass rule (in code) | What it means for us |
|---|---|---|
| **Hot now** | present evidence high | the investable present; goes through the weekly stages (§6) |
| **Hot later: next (1–3 years)** | future evidence high and rising, present evidence still low; late-stage rounds and first products | first in line to move up |
| **Hot later: far (3–5+ years)** | future evidence rising: mostly research, early-stage rounds and visionaries | keep an eye on it; no action |
| **Moving up** | a hot-later theme whose present evidence starts rising | a new domain: add it to **watch** (§4) and build its source map |
| **Cooling** | future evidence falling: fewer raises, VCs and visionaries moving on, forecasts slipping | less interest; a pool domain on this list gets a review flag |

A theme can be hot now and cooling at the same time: the market still pays for it, but the early money has moved on. The radar marks that as **late**. It's the doc's warning about what rose fast.

Each row shows:
- the theme and its list
- a trend arrow (↑ → ↓)
- the evidence counts behind it
- what changed since last month

New themes come from the emerging-term check on the horizon sources (5.7, step 6); the LLM only names them. The thresholds, and how the radar feeds the weekly proposals, will be reviewed with Part B.

## 6. Part B: lifecycle stages (to be reviewed later)

Sections 6–8 are the analysis part. They stay as a first draft and will be reviewed separately.

Each domain gets three scores (0–100). Each score is built from standardized signals, compared both with the domain's own history and with other domains:

| Score | Built from |
|---|---|
| Attention | level and 4/12-week change in the attention metrics (5.9), mentions by category (5.7) and the VC, government and research signals (5.4, 5.6) |
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

## 7. Part B: from domain to tickers

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

## 8. Part B: recommendation rules

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
assets/pool.yaml                  current pool (in git; history = commits)
assets/themes.yaml                tracked themes: names, search terms, ETFs, parent theme (in git)
assets/sources/common/*.yaml      fetcher specs every domain uses (in git)
assets/sources/horizon/*.yaml     general horizon sources: VCs, visionaries, forecasters, government R&D (in git)
assets/sources/<domain>/*.yaml    each domain's source map (in git; you review it)
assets/sources/plugins/*.py       reviewed custom fetchers (rare)
data/fetch.db                     SQLite: documents, metrics, fetch runs, fetcher health, reach scores
data/raw/<fetcher>/<date>.*       raw responses, kept for re-parsing and repair
data/scout.db                     SQLite: theme_signals (weekly, point-in-time), theme_members,
                                  fundamentals, analyst_snapshots, scans, proposals, your verdicts
data/scout/radar-<YYYY-MM>.md     monthly radar: hot now / hot later / cooling (5.13)
data/scout/<YYYY-MM-DD>.md        scan reports
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
    coverage-checklist.md   the categories in 5.4 and how to research each one
    fetcher-specs.md        the spec format, the fetcher types and the validator's checks
    lifecycle.md            stage rules and thresholds, with worked examples (Part B)
    dossier-rubric.md       judging fundamentals, analysts, valuation, plans (Part B)
    report-template.md
  evals/
src/investing/fetch/        the fetcher engine, shared by both skills
  engine.py  scheduler.py  validator.py  health.py
  types/                    rss.py  json_api.py  bulk_file.py  sitemap.py  html_list.py  diff_page.py
  process.py                normalize, de-duplicate, extract text, tag, count (5.7)
  bursts.py                 emerging-term detection (5.7, step 6)
  reach.py                  analyst reach score (5.5)
src/investing/scout/
  cli.py                    signals | money | stage | map | fundamentals | analysts | report-data | apply-pool | radar
  signals.py                weekly theme signals from the fetched documents and metrics
  money.py                  relative strength, breadth, volume, betas, correlations
  mapping.py                ETF holdings, filing mentions, industry codes, purity
  fundamentals.py           SEC XBRL company facts → metrics, point-in-time
  analysts.py               weekly snapshots → revisions
  radar.py                  hot now / hot later / cooling lists (5.13)
src/investing/common/       http, prices, storage (shared with investing.news)
```

The frontmatter follows the same conventions as `asset-news`, which were checked on 2026-11-19 (plan_scraper §10):

```yaml
---
name: domain-scout
description: Scans the web and the market for emerging, strengthening, overheated and fading domains, maps their tickers with fundamentals, analyst views and business plans, and proposes changes to the followed pool. Also publishes a monthly hot-now / hot-later radar, builds each domain's source map and repairs broken fetchers.
argument-hint: "[--as-of DATE] [--deep \"<domain>\"] [--ticker TICKER] [--sources \"<domain>\" | horizon] [--repair] [--radar]"
disable-model-invocation: true
shell: powershell
allowed-tools: PowerShell(.\.venv\Scripts\python.exe -m investing.scout *), PowerShell(.\.venv\Scripts\python.exe -m investing.fetch *), WebSearch, WebFetch, Edit(data/**), Edit(assets/sources/**/*.yaml)
---
```

**What's pre-approved and what isn't:**
- Fetcher specs are pre-approved, because they're declarative, start as `candidate`, and go live only after validation and your review of the domain's map.
- Plugins (`assets/sources/plugins/`), `pool.yaml` and `themes.yaml` are deliberately left out, so changing them always asks you.

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
- **Radar lead time:** months from a theme's first "hot later" listing to "hot now"

Avoid three look-ahead traps:
- **Today's ETF holdings** didn't exist back then. Use filing mentions and N-PORT holdings as of the date.
- **Restated fundamentals.** Use XBRL values by filing date.
- **Survivorship.** Delisted companies are missing from current lists, so keep them in the store.

### 12.2 Skill evals on frozen data

| Case | Situation | A good result |
|---|---|---|
| source-map | `/domain-scout --sources "nuclear power"` | every applicable checklist category covered; every spec validates; no paid, login or paywalled source; each source has a `why` |
| repair | a fetcher whose page layout changed | a repaired spec that passes the validator, or a clear "retire" with the reason |
| radar-later | a month where a theme's VC and visionary signals rise but its stocks haven't moved | listed as hot later with its evidence counts; not proposed for the pool |
| radar-late | a pool domain whose VC raises and visionary mentions fall while its stocks still rise | flagged hot now but cooling ("late"), with a review flag |
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

### 12.4 Collection tests (no LLM)

| Test | What it checks |
|---|---|
| Determinism | re-parsing the saved raw responses gives identical documents and numbers |
| Validator | each new spec fetches twice, finds a date for at least 90% of its items, respects robots.txt and its rate limit, and fills every field it declares |
| Health | simulated failures mark a fetcher `broken`, and it shows up in `--repair` |
| Cost | collection runs make zero LLM calls |

## 13. Build phases

| Phase | Build | Done when |
|---|---|---|
| 0. Groundwork | shared with `asset-news` Phase 0, plus `src/investing/common/` (prices, http, storage) | prices for SPY and the seed ETFs load into the store |
| 1. Fetch engine | spec format and validator; `rss`, `json_api`, `bulk_file` and `diff_page` types; politeness; health; storage; processing steps 1–5 (5.7); the cross-domain fetchers (5.9) | 20+ fetchers run daily for a week with no LLM and no failures, and re-parsing the raw responses gives identical output |
| 2. Money map | `themes.yaml` seed; money signals per theme ETF (5.10); a weekly table of rising and fading domains | the table looks sensible to you |
| 3. Horizon layer + radar | general horizon sources (5.6) via `--sources horizon`; reach score (5.5); emerging-term flags (5.7, step 6); the monthly radar (5.13) | the first radar lists hot-now, hot-later and cooling themes with their evidence, and at least one theme outside `themes.yaml` comes from the horizon sources |
| 4. Domain source maps + repair | `--sources` with the coverage checklist, first for 3 pilot domains (§15), then for every pool domain; `sitemap` and `html_list` types; `--repair`; snowball discovery; ETF flows and 13F; quarterly source review | each pilot domain covers every category that applies and you approve its map; a deliberately broken spec gets repaired and re-validated |
| 5. Analysis (Part B) | stages, discovery, ticker mapping, dossiers, proposals, hand-off (§6–8), planned in detail later | reviewed separately |
| 6. Backtest + automation | point-in-time replays (§12.1); threshold tuning; weekly unattended runs, set up like asset-news (plan_scraper §13.1), with proposals waiting for your approval | the backtest flags at least 2 of the 3 historical themes before their breakout, with a false-positive rate you accept |

## 14. Risks

| Risk | Mitigation |
|---|---|
| LLM-written fetchers do something wrong or unsafe | declarative specs run by a fixed engine; plugins only after your review; the validator runs before anything goes live; each fetcher only touches its own host |
| Sites change and fetchers break | RSS and APIs first; health checks; repair from the last good raw response |
| Terms of use | robots.txt check in the validator; a terms note per spec; no logins, paywalls or headless browsers; personal use only |
| Echo chamber (popular analysts repeat each other) | the originality score (5.5); primary data in every domain's map |
| Chasing hype (FOMO) | lifecycle stages, persistence rules, overheated flag, churn cap |
| Look-ahead bias in backtests | point-in-time signals; XBRL company facts by filing date (not the frames API); N-PORT holdings as of the date |
| Degraded or undocumented sources (GDELT gaps in Nov 2026; EDGAR full-text search has no official API contract) | data-quality checks for gaps and totals; a fallback for every attention signal; source-health report |
| Survivorship bias | keep delisted tickers in the store |
| Vague themes ("AI") | hierarchical themes, each with an ETF or basket |
| Low-quality small caps in hot themes | size and liquidity filters; dilution, going-concern and restatement flags |
| Unofficial data breaks (Yahoo) | SEC XBRL for fundamentals; Finnhub as a fallback for analyst data |
| Thin free analyst data | weekly snapshots build our own revisions history |
| Recommendations read as advice | it's a personal research tool and you decide; see plan_scraper §15.1 on public use |

## 15. Open decisions

**Agreed on 2026-11-19:** the pool as described in §4: limits, filters, and the `pool` / `watch` / `removed` tiers.

**Open:**
1. **Pilot domains for the source maps (Phase 4):** I suggest semiconductors, power/nuclear and biotech. They need very different sources (trade data, grid data, clinical trials), so they test the checklist well.
2. **Full text:** for freely readable articles, store the full text for the analysis part, or only titles and summaries? Full text gives the analysis more to work with but takes more space. It stays on this PC either way.
3. **Plugins:** allow LLM-written plugin fetchers at all (each reviewed by you), or specs only?
4. **Fetch cadence:** news and blogs daily, metrics weekly, bulk files monthly or quarterly?
5. **Scan cadence:** a weekly scan plus a monthly deep review? On which weekday?
6. **Skill name:** is `domain-scout` OK?
7. **Starting pool:** do you already follow some domains or tickers? They would seed `pool.yaml`.
8. **Radar:** monthly, with about 15 themes per list? Are the horizons right: now, next (1–3 years), far (3–5+ years)?

## 16. To verify

### 16.1 Market and company sources: done 2026-11-19

All 12 sources were checked on 2026-11-19. Live test calls went to SEC XBRL, EDGAR full-text search, Wikimedia, GDELT, Hacker News, arXiv, N-PORT and all five ETF issuers. The results are folded into §5 and §14.

What changed from the first draft:
- GDELT is degraded right now.
- Google Trends is out.
- The XBRL frames API isn't point-in-time.
- XBRL has no segment data.
- Finnhub's targets and estimates are premium.
- Hacker News and arXiv were added as tech-attention signals.
- ETF flows have to be built from daily snapshots.

Still open:
- [ ] `yfinance` analyst data and Sector/Industry lists tested live on our version (1.2, Python 3.9)
- [ ] Finnhub and Massive endpoints tested with real keys
- [ ] Terms of the ETF issuers' sites (only SPDR's file footer was read)
- [ ] Whether GDELT's gaps are temporary
- [ ] Whether the 2026 N-PORT proposal (keep public data quarterly) has been finalized

### 16.2 New free sources for Part A: done 2026-11-19

All 23 sources were tested live. The results are folded into §5.4, §5.5, §5.6 and §5.12.

What changed:
- **Out:** PatentsView is gone, and Metaculus now needs a login.
- **Workarounds:** the SBIR API is down, but its monthly bulk file works. DoD contracts give headlines only.
- **Manual for now:** Korea's 10-day exports (Korean press releases), and the annual reports from sites that block scripts (downloaded once a year).
- **Rare:** podcast transcripts.
- **All free and working:** Form D, YC (community JSON), Substack, YouTube, Apple charts, Tranco, EIA, DefiLlama, H-1B data, regulations.gov, Manifold and Epoch AI.

Still open:
- [ ] Grid queues from PJM, MISO and ERCOT: blocked to scripts from here, which may depend on location
- [ ] Terms on automated access for Substack, Medium, the yc-oss data and Semantic Scholar
- [ ] Whether Semantic Scholar still issues free keys
- [ ] The test hand-checks from plan_scraper §16.1 also apply here, plus one more: `Edit(assets/sources/**/*.yaml)` matches spec files but not plugins
