# Luis Diaz Busquets

The personal site of a finance student at Bryant University (graduating May 2027): experience, certifications and the projects behind them, in English and Spanish.

**Live site:** https://ldiazbusquets.github.io/

## The three sites

| Site | What it is | Repository |
|---|---|---|
| **Portfolio** (this one) | Background, experience, certifications, résumé and project write-ups | this repo |
| **[LDB Finance](https://ldiazbusquets.github.io/finance/)** | Company research, valuation models and market data, with every number checkable | [finance](https://github.com/ldiazbusquets/finance) |
| **[LDB Lab](https://ldiazbusquets.github.io/lab/)** | An applied-AI lab where every model runs in the browser | [lab](https://github.com/ldiazbusquets/lab) |

## Pages

| Page | What it is |
|---|---|
| `index.html` | Home: about, experience, certifications, projects and contact, in English and Spanish |
| `argus.html` | ARGUS Portfolio Planner: efficient frontier, CAPM beta, Monte Carlo simulation and ETF look-through |
| `agents.html` | LADON and HERETIC, automated portfolio research agents |
| `bot.html` | A paper-trading bot's rules, with a year-to-date backtest on real prices |
| `costco.html` | Costco (COST) equity research, FIN 370 coursework |
| `excel.html` | An Excel reference guide |

## How it works

- Plain HTML, CSS and JavaScript, served by GitHub Pages. There is no build step, framework or server, and no cookies or tracking.
- The theme follows the clock: light from 7 am to 7 pm and dark otherwise, with a toggle in the header. Spanish text is stored in `data-es` attributes and swapped in place.
- `backtest.py` runs every weekday after the U.S. close in `.github/workflows/backtest.yml`. It downloads daily prices with `yfinance`, applies the bot's swing rules from January 1, and writes `backtest.json`, which `bot.html` reads.

## Run it locally

```
python3 -m http.server 8000
# open http://localhost:8000
```

To refresh the backtest by hand:

```
pip install yfinance pandas
python3 backtest.py
```

## Notes

Nothing on these sites is investment advice. The trading results are simulated.
