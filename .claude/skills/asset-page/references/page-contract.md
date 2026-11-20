# The page data contract

`UI/pipeline/asset_page.py` writes this data and `UI/static/app.js` reads it, so change them together. When a change isn't backward compatible, bump `SCHEMA` in both files. The page warns when its data uses a newer schema than it understands.

## Top level of `UI/data/<TICKER>.json`

The `.js` file holds the same object, assigned to `window.INVESTING_DATA["<TICKER>"]`.

| Field | Type | Notes |
|---|---|---|
| schema | int | currently 1 |
| ticker, name, kind | str | kind is Yahoo's quoteType (EQUITY, ETF, …) |
| exchange, currency, classification, note | str or null | currency is the trading currency; it sets the money formats |
| domain | str or null | the asset's domain, shown on My watchlist: `domain` in its config.json, else Yahoo's industry (a fund's category) |
| updated_at | ISO time, UTC | |
| source | str | shown in the footer |
| compare | list of {symbol, label, why} | the comparison series |
| quote | {price, previous_close, change, change_pct, market_state, last_close_date, extended?} | extended is {label, price, change_pct}, for pre-market or after hours |
| kpis | list of items | the 6 tiles under the header |
| series | {"1Y", "3M", "1D"} | the price windows (below) |
| ratios, econometrics | list of groups | the two panels |
| warnings | list of str | shown above the footer |
| analyst_actions? | {since, rows, changes, pending} | the analyst updates of the past year, for the rating changes page (stocks only) |

**Analyst update** (one row, newest first): `{date, firm, action, rating, previous, prior_target, target, rating_changed, target_changed, searched?, why?, why_basis?, why_source?, why_url?}`
- `action` is upgrade, downgrade, new coverage, maintained or reiterated.
- `rating_changed` is true for an upgrade, a downgrade or new coverage. `target_changed` is true when the price target moved.
- A row with either is a change: only changes get `searched` and a reason, and `changes` counts them. A plain reiteration gets neither.
- `searched` is false until the `rating_change_cause_searcher` skill has looked into the change. `pending` counts those.
- `why` is the firm's reason in one line, or null when none was found.
- `why_basis` is "reported" (an article gives the reason) or "inferred" (the timing ties it to an event, such as results).
- `why_source` and `why_url` are the article.
- The update copies these from the kept table, `UI/asset/<slug>_page/analyst_table.json`, and searches nothing itself. Each row there is keyed by `"<date>|<firm>|<rating>|<previous>"`.

The Analysts group in `ratios` has `"id": "analysts"`; the page adds its button to the rating changes page there.

**Item:** `{label, value, fmt, note?, hint?}`
- `note` shows under the value; `hint` shows under the label.
- `value` is null when unknown, and the page shows "—".

**Group:** `{title, id?, note?, items: [item]}`

## Formats (`fmt`)

| fmt | value | Shown as |
|---|---|---|
| money | number | $15.24, in the asset's currency |
| money_compact | number | $6.47B |
| money_range | [low, high] | $23.00 – $139.00 |
| pct | fraction | 23.2% |
| pct_signed | fraction | +12.3%, −5.0% |
| x | number | 9.31× |
| num | number | 1.78 |
| int | number | 19 |
| int_compact | number | 424M |
| days | number | 1.8 days |
| date | YYYY-MM-DD | Feb 4, 2027 |
| text | string | as given |

`usd` and `usd_compact` still work, and always mean dollars.

## Series

`{interval: "1d" | "1m", ref_label, points: [point], vr_label?, session?, prev_close?, session_close?}`

**Point:** `{t, o, h, l, c, v, ref, vr?}`
- `t` is `YYYY-MM-DD` for daily bars, or `HH:MM` US Eastern for minute bars.
- `ref` is the moving average on daily bars, or VWAP on minute bars.
- `vr` is the day's volume divided by the previous 20 sessions' average (daily only).

On the "1D" series:
- `session` is the session's date.
- `prev_close` is the prior session's close.
- `session_close` is the official close, once the session has ended.

## Changing the contract

- **Adding an optional field** needs no version change: the page ignores a field until it reads it.
- **Renaming or removing a field, or changing what one means,** needs a new `SCHEMA` in both files.
