"""
Year-to-date backtest of the paper trading bot's swing rules.

This runs automatically on GitHub (see .github/workflows/backtest.yml) every
weekday after the market closes. It downloads real daily prices, applies the
bot's rules from January 1 to today, and writes backtest.json, which bot.html
reads to show the "Year to date" section.
"""
import json, datetime as dt
import pandas as pd

UNIVERSE = ["NVDA", "MSFT", "AMD", "META", "AAPL", "GOOGL", "AMZN", "AVGO", "JPM", "COST", "LLY", "XOM"]
BENCH = "SPY"
START_EQUITY = 100_000
RISK_PER_TRADE = 0.01      # 1% of equity at risk per trade
STOP_PCT = 0.07            # hard stop 7% below entry
TP1, TP2 = 0.05, 0.10      # sell half at +5%, the rest at +10%
TRAIL = 0.03               # after TP1: stop to breakeven, then trail 3% below the high
TIME_STOP_DAYS, FLAT = 10, 0.015
MAX_POS_FRAC, MAX_OPEN = 0.20, 5
COMMISSION = 0.005         # dollars per share


def indicators(df):
    c = df["Close"]
    df["ema21"] = c.ewm(span=21, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + up / dn.replace(0, 1e-9))
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    df["mh"] = macd - macd.ewm(span=9, adjust=False).mean()
    df["vavg"] = df["Volume"].rolling(20).mean()
    return df


def entry_signal(df, i):
    r, p = df.iloc[i], df.iloc[i - 1]
    return bool(
        r.Close > r.ema50 and r.ema21 > df.ema21.iloc[i - 5]          # uptrend
        and r.Low <= r.ema21 * 1.015 and r.Close >= r.ema21           # pullback to the 21 EMA that holds
        and 40 <= r.rsi <= 60 and r.rsi > p.rsi                       # RSI reset and turning up
        and r.mh > p.mh                                           # MACD histogram turning up
        and r.Volume < r.vavg                                         # quiet pullback volume
    )


def run(data, bench, start):
    days = [d for d in bench.index if d >= start]
    cash, open_pos, trades, curve = START_EQUITY, {}, [], []
    b0 = bench.Close.loc[days[0]]
    for day in days:
        for t in list(open_pos):                                      # manage open positions
            df = data[t]
            if day not in df.index: continue
            r, pos = df.loc[day], open_pos[t]
            pos["days"] += 1; pos["high"] = max(pos["high"], r.Close)
            def sell(sh, px, why):
                nonlocal cash
                cash += sh * px - sh * COMMISSION
                pos["pnl"] += sh * (px - pos["entry"]) - sh * COMMISSION
                pos["shares"] -= sh; pos["why"] = why
            if r.Low <= pos["stop"]:
                sell(pos["shares"], min(pos["stop"], r.Open), "stop")
            else:
                if not pos["tp1"] and r.High >= pos["entry"] * (1 + TP1):
                    sell(pos["shares"] // 2, pos["entry"] * (1 + TP1), "tp1"); pos["tp1"] = True; pos["stop"] = pos["entry"]
                if pos["shares"] and r.High >= pos["entry"] * (1 + TP2):
                    sell(pos["shares"], pos["entry"] * (1 + TP2), "tp2")
                elif pos["tp1"]:
                    pos["stop"] = max(pos["stop"], pos["high"] * (1 - TRAIL))
                if pos["shares"] and pos["days"] >= TIME_STOP_DAYS and abs(r.Close / pos["entry"] - 1) < FLAT:
                    sell(pos["shares"], r.Close, "time")
            if pos["shares"] == 0:
                trades.append({"ticker": t, "in": pos["date"], "out": str(day.date()), "entry": round(pos["entry"], 2),
                               "pnl": round(pos["pnl"], 2), "exit": pos["why"]}); del open_pos[t]
        equity = cash + sum(p["shares"] * data[t].Close.asof(day) for t, p in open_pos.items())
        for t in UNIVERSE:                                            # look for new entries
            df = data.get(t)
            if df is None or t in open_pos or len(open_pos) >= MAX_OPEN or day not in df.index: continue
            i = df.index.get_loc(day)
            if i < 60 or not entry_signal(df, i): continue
            if bench.Close.loc[day] < bench.ema50.loc[day]: continue  # skip when the market is in a downtrend
            px = df.Close.iloc[i]; stop = px * (1 - STOP_PCT)
            sh = int(min(equity * RISK_PER_TRADE / (px - stop), equity * MAX_POS_FRAC / px, cash / px))
            if sh < 1: continue
            cash -= sh * px + sh * COMMISSION
            open_pos[t] = {"entry": px, "stop": stop, "shares": sh, "tp1": False, "high": px, "days": 0,
                           "pnl": -sh * COMMISSION, "date": str(day.date()), "why": ""}
        equity = cash + sum(p["shares"] * data[t].Close.asof(day) for t, p in open_pos.items())
        curve.append([str(day.date()), round(equity, 2), round(START_EQUITY * bench.Close.loc[day] / b0, 2)])
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]; losses = [-t["pnl"] for t in trades if t["pnl"] <= 0]
    eq = pd.Series([c[1] for c in curve])
    return {
        "generated": str(dt.date.today()), "start": curve[0][0], "end": curve[-1][0], "universe": UNIVERSE,
        "startEquity": START_EQUITY, "endEquity": curve[-1][1],
        "returnPct": round((curve[-1][1] / START_EQUITY - 1) * 100, 2),
        "benchReturnPct": round((curve[-1][2] / START_EQUITY - 1) * 100, 2),
        "trades": len(trades), "openPositions": len(open_pos),
        "winRate": round(100 * len(wins) / len(trades), 1) if trades else 0,
        "profitFactor": round(sum(wins) / sum(losses), 2) if losses and sum(losses) else None,
        "maxDrawdownPct": round(float(((eq / eq.cummax()) - 1).min()) * 100, 2),
        "curve": curve, "tradeList": trades[-40:],
    }


if __name__ == "__main__":
    import yfinance as yf
    year = dt.date.today().year
    raw = yf.download(UNIVERSE + [BENCH], start=f"{year - 1}-06-01", auto_adjust=True, group_by="ticker", progress=False)
    data = {t: indicators(raw[t].dropna().copy()) for t in UNIVERSE}
    bench = indicators(raw[BENCH].dropna().copy())
    result = run(data, bench, pd.Timestamp(f"{year}-01-01"))
    json.dump(result, open("backtest.json", "w"))
    print(f"{result['start']} to {result['end']}: bot {result['returnPct']}% vs {BENCH} {result['benchReturnPct']}%, "
          f"{result['trades']} trades, win rate {result['winRate']}%, max drawdown {result['maxDrawdownPct']}%")
    print("Wrote backtest.json")
