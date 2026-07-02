# EMA Trend-Following Strategy — Gold (XAU/USD)

> ⚠️ **DISCLAIMER — READ FIRST**
> This software is for **educational and testing purposes only**. It is not
> financial advice. **Past backtest performance does not guarantee future
> results.** Trading leveraged products involves substantial risk of loss.
> Test extensively in PAPER mode on a DEMO account before ever considering
> real funds. You alone are responsible for any live trading you enable.

## Strategy rules
- **Timeframe:** 1H (configurable in `config.json`)
- **Long:** EMA20 crosses above EMA50 + price > EMA200 + ADX(14) > 25 → enter next candle open
- **Short:** mirror image
- **Stop:** 1.5×ATR(14) · **Target:** 3×ATR(14) (2:1) · optional EMA50 trailing (`exit_mode: "trailing"`)
- **Always:** exit if EMA20/50 cross back against the position
- **Risk:** 1% equity/trade, 1 position max, −3% daily stop, 15% drawdown halt
- **Filters:** low-liquidity hours skip + manual news blackout list (v1)

## Files
| File | Purpose |
|------|---------|
| `config.json` | ALL parameters — EMAs, ADX, ATR multiples, risk %, spread, hours, `live_trading` flag |
| `strategy.py` | Indicators + rules (shared by both modes — no drift) |
| `backtest.py` | Backtest engine → metrics, `backtest_trades.csv`, `equity_curve.png` |
| `trader.py` | Paper/live trader on MT5 (paper by default) |

## Usage (from repo root)
```
python ema_gold/backtest.py                 # backtest per config.json
python ema_gold/backtest.py --years 6       # longer period
python ema_gold/backtest.py --exit-mode trailing
python ema_gold/trader.py                   # PAPER trading (no real orders)
```

## Going live (only after paper-testing)
1. Verify weeks of paper results in `paper_trades.csv`.
2. Set `"live_trading": true` in `config.json`.
3. MT5 terminal must be open, logged in, Algo Trading enabled.
4. Note: the repo's other bot (`mt5_trader.py`) also trades GOLD — run only
   ONE gold-trading bot live at a time or they will fight.

## Data
- Default source: your MT5 terminal (25 years of H1 GOLD available).
- Alternatives: `data_source: "csv"` (+ `csv_path`) or `"yfinance"` (≤730d).
- Backtest includes spread + slippage simulation (`spread_usd`, `slippage_usd`).
