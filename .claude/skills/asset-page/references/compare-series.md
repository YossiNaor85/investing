# Choosing comparison series

The page measures beta (sensitivity) and correlation against each comparison series. Pick the series that move the stock; they can differ from what Yahoo's labels suggest.

## The three slots

| Slot | What it is | Default |
|---|---|---|
| Market | the broad market the stock trades in; beta, and the "market part" of each day's move, are measured against it | SPY for US listings |
| Domain | the ETF of the business the stock is really in (its domain, in the doc's sense) | from its industry (table below) |
| Driver (optional) | one price that drives its revenue or sentiment | only when the business clearly depends on it |

Keep it to 2–3 series. More make the page noisier without telling you more.

## Prefer ETFs

Use US-listed ETFs, even for commodities:
- They trade on the same days as the stock, so daily returns line up.
- A futures contract (`CL=F`) jumps at each roll, and a yield index (`^TNX`) is a level rather than a price. Beta against either is meaningless.

Crypto is the exception: use the spot pair (`BTC-USD`). The engine matches its returns to US trading days.

## Domain ETFs by industry

| Industry | ETF |
|---|---|
| Semiconductors, AI hardware | SMH |
| Software | IGV |
| Internet and mega-cap tech | QQQ (as the domain, not the market) |
| Biotech | XBI |
| Pharmaceuticals | XPH |
| Medical devices | IHI |
| Regional banks | KRE |
| Large banks | KBE |
| Insurance | KIE |
| Oil and gas producers | XOP |
| Oil services | OIH |
| Integrated oil | XLE |
| Gold miners | GDX |
| Silver miners | SIL |
| Copper miners | COPX |
| Uranium and nuclear fuel | URA |
| Homebuilders | ITB |
| REITs | VNQ |
| Aerospace and defense | ITA |
| Airlines | JETS |
| Utilities | XLU |
| Solar | TAN |
| Retail | XRT |
| Crypto miners | WGMI, with BTC-USD as the driver |

For anything else, use the sector SPDR: XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLRE, XLB, XLC.

## Drivers

| The business depends on | Driver |
|---|---|
| Bitcoin (miners, treasury companies, exchanges) | BTC-USD |
| Crude oil | USO |
| Natural gas | UNG |
| Gold | GLD |
| Copper | CPER |
| Interest rates (banks, REITs, homebuilders, utilities) | TLT |
| The dollar (exporters, commodities) | UUP |

## When Yahoo's label misleads

Yahoo classifies companies by legal or historical category, which can lag behind the business. Go by the business, and read the summary in `inspect`'s `business` field.

IREN is the worked example. Yahoo calls it "Financial Services · Capital Markets", but the stock moves with AI infrastructure and with bitcoin. Its config:

| Series | Why |
|---|---|
| SPY | the market |
| SMH | IREN's AI cloud (GPU) business trades with the AI chip complex |
| BTC-USD | bitcoin mining revenue |

## Listings outside the US

- Use the home market's index as the market, e.g. `^TA125.TA` for Tel Aviv or `^STOXX50E` for the euro area. Pass it with `--market` and give it a label.
- Keep SPY as a second series if the company is global.
- Tel Aviv prices are in agorot (ILA, 1/100 of a shekel), while Yahoo's company figures are often in USD. The page warns about this; mention it to the user.
