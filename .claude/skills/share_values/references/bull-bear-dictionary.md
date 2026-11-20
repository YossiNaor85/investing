# Bull/bear dictionary, for expert review

Generated from `UI/pipeline/bull_bear_dictionary.json`, the file the code reads, by `.venv/Scripts/python.exe UI/pipeline/share_values.py --dictionary`. Make changes in the JSON, then regenerate this page. The same links apply to every asset.

**Sides:** bears are the pessimistic case, a low valuation. Neutral is an ordinary market, valued at market or sector norms. Bulls are the optimistic case, a high valuation.
| Value | Fundamental | Multiple | Side | Market mood | Why this side |
|---|---|---|---|---|---|
| net_cash | Net cash (cash minus all debt) | 1× | bears | Capitulation: only the cash left after paying all debt counts | Gives the business itself no value: only cash net of every debt remains. It is the liquidation floor bears point to in a panic. |
| tangible_book | Tangible book value | 1× | bears | Crash: priced at its tangible assets alone | Counts only tangible net assets, treats goodwill and intangibles as worthless and adds nothing for earning power: a distressed-sale view. |
| book | Book value | 1× | bears | Deep pessimism: priced at book value, as in a sell-off | A price-to-book of 1 says the business is worth only its accounting net assets, far below the market's usual 3 to 5 times book: the classic bear floor. |
| revenue_bears | Revenue, last four quarters | 1× | bears | Pessimism: each dollar of yearly revenue priced at a dollar | One times revenue is below the S&P 500's long-run price-to-sales of about 1.5 to 2 and well below its recent level near 3: priced like a low-margin or shrinking business. |
| revenue_market | Revenue, last four quarters | 3× | neutral | An ordinary market: revenue valued near the S&P 500's recent multiple | About three times revenue is where the S&P 500 as a whole has traded in recent years: neither a discount nor a premium. |
| revenue_bulls | Revenue pace (last quarter × 4) | 10× | bulls | Growth enthusiasm: the newest quarter's pace, at a growth-stock multiple | Two optimistic choices at once: the latest quarter's revenue annualized, as if growth holds, and a price-to-sales of 10, which only fast growers command. |
| earnings_bears | Earnings, last four quarters | 12× | bears | Pessimism: earnings priced like a value stock | A P/E of 12 is below the S&P 500's long-run average of about 16 and its recent 20 to 25: the multiple of a stock the market expects little from. |
| earnings_market | Earnings, last four quarters | S&P 500's P/E (live) | neutral | An ordinary market: earnings valued like the S&P 500 today | The S&P 500's own trailing P/E today, live from Yahoo (SPY): the average stock's multiple, neutral by definition. |
| earnings_sector | Earnings, last four quarters | sector ETF's P/E (live) | neutral | In step with its sector: earnings valued like its sector today | The trailing P/E of the asset's sector ETF today (its comparison series), live from Yahoo: valued like its peers, no better and no worse. |
| earnings_bulls | Earnings, last four quarters | 35× | bulls | Optimism: a growth premium on earnings | A P/E of 35 is well above the market's: investors pay it only when they expect earnings to grow fast for years. |
| ebitda_bears | EBITDA, last four quarters | 8× | bears | Pessimism: operating earnings at a low multiple | An enterprise value of 8 times EBITDA is below the market's usual 12 to 16: priced like a mature or troubled business. |
| ebitda_market | EBITDA, last four quarters | 14× | neutral | An ordinary market: operating earnings at a typical multiple | About 14 times EBITDA is close to the S&P 500's average in recent years, around 12 to 16. |
| ebitda_bulls | EBITDA, last four quarters | 25× | bulls | Optimism: operating earnings at a growth multiple | 25 times EBITDA is a growth-company multiple, paid when investors expect operating earnings to rise fast. |
| fcf_bears | Free cash flow, last four quarters | 12× | bears | Pessimism: free cash flow priced to yield about 8% | 12 times free cash flow is a free-cash-flow yield of about 8%, roughly double the market's: the price of a stock investors distrust. |
| fcf_market | Free cash flow, last four quarters | 22× | neutral | An ordinary market: free cash flow priced to yield about 4.5% | 22 times free cash flow, a yield of about 4.5%, is close to the market's long-run free-cash-flow yield of 4 to 5%. |
| fcf_bulls | Free cash flow, last four quarters | 40× | bulls | Optimism: free cash flow priced to yield 2.5%, paying for growth | 40 times free cash flow, a 2.5% yield, makes sense only if the cash flow is expected to grow fast. |
