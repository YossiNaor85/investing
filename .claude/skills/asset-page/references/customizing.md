# Customizing one asset's page

Each asset's update script has a `customize(data, ctx)` function. It runs after the standard build and returns the data. Put anything only this asset needs there, so the shared engine stays the same for every page.

`ctx` holds:

| Key | What |
|---|---|
| config | the asset's config.json |
| info | Yahoo's company data (a dict) |
| history | 2 years of daily bars (a pandas DataFrame with Open, High, Low, Close, Volume) |
| intraday | the latest session's 1-minute bars, or None |
| compare | {symbol: daily closes} for the comparison series |

## Examples

Add a group to the econometric measures:

```python
def customize(data, ctx):
    btc = ctx["compare"].get("BTC-USD")
    if btc is not None and len(btc) > 22:
        data["econometrics"].append({
            "title": "Bitcoin",
            "items": [{"label": "BTC, 1-month change", "value": float(btc.iloc[-1] / btc.iloc[-22] - 1),
                       "fmt": "pct_signed"}],
        })
    return data
```

Replace a headline tile:

```python
def customize(data, ctx):
    data["kpis"][5] = {"label": "Short interest", "value": ctx["info"].get("shortPercentOfFloat"), "fmt": "pct"}
    return data
```

Values must fit the data contract (`page-contract.md`). The engine cleans NaN to null on its own.

## When to change the engine instead

A change belongs in `UI/pipeline/asset_page.py` when every asset should get it, such as a new ratio group or measure. After changing the engine:

1. Run each asset's update script (`new_page.py list` shows them).
2. Run `new_page.py check` on IREN and on one ETF.
3. If the output format changed, update `UI/static/app.js` and `page-contract.md` too.

## Changing the skill itself

| To change | Edit |
|---|---|
| Steps and rules | `SKILL.md`. Keep it short. |
| Judgment guides | the files in `references/`, e.g. `compare-series.md` for new industries |
| Commands | `UI/pipeline/new_page.py` |
| What a new asset's script looks like | the template, `UI/pipeline/templates/update_page.py.tmpl` |

A template change only affects assets created after it. Existing scripts keep their `customize()` code, so edit them by hand if the code around it changes.

Test changes on a copy of the UI:
1. Copy `index.html`, `static/` and `pipeline/` into a scratch folder.
2. Run `new_page.py --ui-dir <copy> create <TICKER> ...`.

The real "Your assets" stays untouched.
