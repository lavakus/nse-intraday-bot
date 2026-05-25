"""
SMC/ICT Strategy Backtester
============================
Walk-forward backtest on Gold (XAUUSD) and Bitcoin (BTC-USD)
using the EXACT same scoring logic as the live trading bot.

How it works:
  - Downloads historical OHLCV data from Yahoo Finance
  - Walks forward bar-by-bar (no lookahead bias)
  - At each bar: runs score_gold() / score_btc() on past data
  - If score >= threshold: records signal, entry, SL, TP
  - Checks future 15m bars: first hit (TP = WIN, SL = LOSS)
  - Reports: Win Rate, Profit Factor, Expectancy, breakdown by score

Usage:
    python backtest.py              # Gold + BTC, last 60 days
    python backtest.py --asset GOLD
    python backtest.py --asset BTC
    python backtest.py --days 45
"""

import sys
import argparse
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone

warnings.filterwarnings("ignore")

IST = timezone(timedelta(hours=5, minutes=30))


# ═══════════════════════════════════════════════════════════════════
# DATA HELPERS
# ═══════════════════════════════════════════════════════════════════

def fetch(ticker: str, interval: str, days: int) -> pd.DataFrame:
    """Download OHLCV from Yahoo Finance, return IST-indexed DataFrame."""
    end   = datetime.utcnow()
    # For 15m / 30m data Yahoo enforces strict 60-day limit — no padding
    extra = 0 if interval in ("15m", "30m", "5m") else 5
    start = end - timedelta(days=days + extra)
    try:
        df = yf.download(
            ticker, start=start, end=end,
            interval=interval, auto_adjust=True,
            progress=False, threads=False
        )
    except Exception as e:
        print(f"  [!] Download error {ticker} {interval}: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    # Flatten multi-level columns (newer yfinance versions)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [c.lower() for c in df.columns]
    df.index   = pd.to_datetime(df.index, utc=True).tz_convert(IST)
    return df.dropna(subset=["close"])


def resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Resample 1H data → 4H OHLCV."""
    r = df_1h.resample("4h").agg({
        "open": "first", "high": "max",
        "low":  "min",   "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    return r


def resample_weekly(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Resample 1H data → Weekly OHLCV."""
    r = df_1h.resample("W").agg({
        "open": "first", "high": "max",
        "low":  "min",   "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    return r


def slice_to(df: pd.DataFrame, ts) -> pd.DataFrame:
    """Return all rows with index <= ts (no lookahead)."""
    return df[df.index <= ts].copy()


def get_pdh_pdl(df_1h: pd.DataFrame, bar_ts) -> tuple:
    """Previous day's high/low from 1H data."""
    prev = (bar_ts - timedelta(days=1)).date()
    rows = df_1h[df_1h.index.date == prev]
    if rows.empty:
        return None, None
    return float(rows["high"].max()), float(rows["low"].min())


# ═══════════════════════════════════════════════════════════════════
# OUTCOME CHECKER  (no lookahead — uses only future bars)
# ═══════════════════════════════════════════════════════════════════

def check_outcome(
    future_15m: pd.DataFrame,
    entry: float, sl: float, tp: float,
    direction: str,
    max_bars: int = 160,   # 160 × 15min ≈ 40 hours
) -> str:
    """Walk future bars. First hit = outcome. Returns WIN / LOSS / OPEN."""
    for _, row in future_15m.iloc[:max_bars].iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG":
            if l <= sl: return "LOSS"
            if h >= tp: return "WIN"
        else:
            if h >= sl: return "LOSS"
            if l <= tp: return "WIN"
    return "OPEN"


# ═══════════════════════════════════════════════════════════════════
# GOLD BACKTESTER
# ═══════════════════════════════════════════════════════════════════

def backtest_gold(days: int) -> list:
    print(f"\n{'='*62}")
    print(f"  GOLD (XAUUSD) Backtest  —  last {days} days")
    print(f"{'='*62}")
    print("  Downloading data from Yahoo Finance...")

    # GC=F = Gold Futures (most liquid Gold ticker on Yahoo Finance)
    df_1h  = fetch("GC=F",      "1h",  min(days + 30, 720))
    df_15m = fetch("GC=F",      "15m", min(days, 50))   # 15m max ~58 days
    df_dxy = fetch("DX-Y.NYB",  "1h",  min(days + 30, 720))

    if df_1h.empty or df_15m.empty:
        print("  [!] Insufficient data — check internet / try fewer days")
        return []

    df_4h = resample_4h(df_1h)
    print(f"  4H: {len(df_4h)} bars  |  1H: {len(df_1h)} bars  |  15m: {len(df_15m)} bars")

    from gold_strategy import score_gold

    results    = []
    last_trade = {}          # direction → last signal bar_ts
    COOLDOWN   = 8 * 3600   # 8 hours cooldown same-direction

    for i, bar_ts in enumerate(df_4h.index.tolist()):
        if i < 20:
            continue  # need lookback

        s4h  = slice_to(df_4h,  bar_ts)
        s1h  = slice_to(df_1h,  bar_ts)
        s15m = slice_to(df_15m, bar_ts)

        if len(s15m) < 30 or len(s1h) < 15:
            continue

        pdh, pdl = get_pdh_pdl(df_1h, bar_ts)

        # DXY confirmation
        sdxy = slice_to(df_dxy, bar_ts)
        dxy_data = None
        if len(sdxy) >= 5:
            d_now  = float(sdxy["close"].iloc[-1])
            d_prev = float(sdxy["close"].iloc[-5])
            dxy_data = {"bearish": d_now < d_prev, "bullish": d_now > d_prev}

        try:
            sig = score_gold(
                df_4h=s4h, df_1h=s1h, df_15m=s15m,
                pdh=pdh, pdl=pdl,
                dxy_data=dxy_data,
                ist_time=bar_ts.to_pydatetime(),
            )
        except Exception:
            continue

        if not sig:
            continue

        direction = sig["direction"]

        # 8-hour cooldown per direction
        prev_ts = last_trade.get(direction)
        if prev_ts and (bar_ts - prev_ts).total_seconds() < COOLDOWN:
            continue

        t1  = sig["trade_params"]["t1"]
        t2  = sig["trade_params"]["t2"]
        sl  = sig["trade_params"]["sl"]
        ent = sig["trade_params"]["entry"]

        future_15m = df_15m[df_15m.index > bar_ts]
        if future_15m.empty:
            continue   # too close to end of dataset

        # Check T1 (partial TP) and T2 (full TP) — WIN if T1 hit before SL
        out_t1 = check_outcome(future_15m, ent, sl, t1, direction)
        out_t2 = check_outcome(future_15m, ent, sl, t2, direction)

        # Primary outcome = T1 (conservative — wins count at 1:2 RR)
        outcome = out_t1
        rr_used = sig["trade_params"]["rr_t1"]

        results.append({
            "asset":     "GOLD",
            "time":      bar_ts.strftime("%Y-%m-%d %H:%M"),
            "direction": direction,
            "score":     sig["score"],
            "entry":     round(ent, 2),
            "sl":        round(sl,  2),
            "t1":        round(t1,  2),
            "t2":        round(t2,  2),
            "tp":        round(t1,  2),   # report T1 as primary TP
            "rr":        round(rr_used, 1),
            "outcome":   outcome,
            "out_t2":    out_t2,          # T2 outcome for reference
        })
        last_trade[direction] = bar_ts

    return results


# ═══════════════════════════════════════════════════════════════════
# BTC BACKTESTER
# ═══════════════════════════════════════════════════════════════════

def backtest_btc(days: int) -> list:
    print(f"\n{'='*62}")
    print(f"  BTC (Bitcoin) Backtest  —  last {days} days")
    print(f"{'='*62}")
    print("  Downloading data from Yahoo Finance...")

    df_1h  = fetch("BTC-USD", "1h",  min(days + 30, 720))
    df_15m = fetch("BTC-USD", "15m", min(days, 59))

    if df_1h.empty or df_15m.empty:
        print("  [!] Insufficient data")
        return []

    df_4h     = resample_4h(df_1h)
    df_weekly = resample_weekly(df_1h)
    print(f"  Weekly: {len(df_weekly)}  |  4H: {len(df_4h)}  |  "
          f"1H: {len(df_1h)}  |  15m: {len(df_15m)}")

    from btc_strategy import score_btc

    results    = []
    last_trade = {}
    COOLDOWN   = 8 * 3600

    for i, bar_ts in enumerate(df_4h.index.tolist()):
        if i < 20:
            continue

        s4h    = slice_to(df_4h,     bar_ts)
        s1h    = slice_to(df_1h,     bar_ts)
        s15m   = slice_to(df_15m,    bar_ts)
        s_week = slice_to(df_weekly, bar_ts)

        if len(s15m) < 30 or len(s4h) < 15:
            continue

        pdh, pdl = get_pdh_pdl(df_1h, bar_ts)

        try:
            sig = score_btc(
                df_weekly=s_week,
                df_4h=s4h,
                df_1h=s1h,
                df_15m=s15m,
                pdh=pdh, pdl=pdl,
                funding={"rate_pct": 0.01},             # neutral for backtest
                fear_greed={"value": 50,                # neutral for backtest
                            "in_ideal_range": True},
                cme_gap={},
                ist_time=bar_ts.to_pydatetime(),
            )
        except Exception:
            continue

        if not sig:
            continue

        direction = sig["direction"]

        prev_ts = last_trade.get(direction)
        if prev_ts and (bar_ts - prev_ts).total_seconds() < COOLDOWN:
            continue

        t1  = sig["trade_params"]["t1"]
        t2  = sig["trade_params"]["t2"]
        sl  = sig["trade_params"]["sl"]
        ent = sig["trade_params"]["entry"]

        future_15m = df_15m[df_15m.index > bar_ts]
        if future_15m.empty:
            continue

        out_t1 = check_outcome(future_15m, ent, sl, t1, direction)
        out_t2 = check_outcome(future_15m, ent, sl, t2, direction)
        outcome  = out_t1
        rr_used  = sig["trade_params"]["rr_t1"]

        results.append({
            "asset":     "BTC",
            "time":      bar_ts.strftime("%Y-%m-%d %H:%M"),
            "direction": direction,
            "score":     sig["score"],
            "entry":     round(ent, 2),
            "sl":        round(sl,  2),
            "t1":        round(t1,  2),
            "t2":        round(t2,  2),
            "tp":        round(t1,  2),
            "rr":        round(rr_used, 1),
            "outcome":   outcome,
            "out_t2":    out_t2,
        })
        last_trade[direction] = bar_ts

    return results


# ═══════════════════════════════════════════════════════════════════
# REPORT PRINTER
# ═══════════════════════════════════════════════════════════════════

def print_report(results: list, asset: str) -> dict | None:
    if not results:
        print(f"\n  [{asset}] 0 signals generated — strategy had nothing to fire on.")
        return None

    closed = [r for r in results if r["outcome"] != "OPEN"]
    wins   = [r for r in closed  if r["outcome"] == "WIN"]
    losses = [r for r in closed  if r["outcome"] == "LOSS"]
    open_  = [r for r in results if r["outcome"] == "OPEN"]

    n_win    = len(wins)
    n_loss   = len(losses)
    n_closed = len(closed)
    win_rate = n_win / n_closed * 100 if n_closed else 0.0

    avg_rr       = float(np.mean([r["rr"] for r in results])) if results else 0
    gross_profit = sum(r["rr"] for r in wins)
    gross_loss   = float(n_loss) or 1e-9
    pf           = gross_profit / gross_loss
    expectancy   = (win_rate / 100 * avg_rr) - (1 - win_rate / 100)

    # max consecutive losses
    streak = max_streak = 0
    for r in closed:
        if r["outcome"] == "LOSS":
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    print(f"\n{'='*62}")
    print(f"  {asset}  —  BACKTEST RESULTS")
    print(f"{'='*62}")
    print(f"  Total Signals      : {len(results)}")
    print(f"  Closed Trades      : {n_closed}  (Still open/pending: {len(open_)})")
    print(f"  Wins               : {n_win}")
    print(f"  Losses             : {n_loss}")
    print(f"  WIN RATE           : {win_rate:.1f}%")
    print(f"  Profit Factor      : {pf:.2f}x  (>1.0 = profitable strategy)")
    print(f"  Avg R:R            : 1:{avg_rr:.1f}")
    print(f"  Expectancy         : {expectancy:+.2f}R per trade")
    print(f"  Max consec loss    : {max_streak}")
    print(f"{'='*62}")

    # ── Score bracket breakdown ──────────────────────────────────
    print(f"\n  Win Rate by Score Range:")
    for lo, hi, label in [
        (60,  74, "60-74 (Weak)  "),
        (75,  89, "75-89 (Good)  "),
        (90, 150, "90+   (Excellent)"),
    ]:
        grp   = [r for r in closed if lo <= r["score"] <= hi]
        g_win = [r for r in grp   if r["outcome"] == "WIN"]
        wr    = len(g_win) / len(grp) * 100 if grp else 0
        bar   = "#" * int(wr / 5)
        print(f"    Score {label}: {len(grp):>2} trades  {wr:>5.1f}%  {bar}")

    # ── Full trade list ──────────────────────────────────────────
    print(f"\n  All Signals ({len(results)} total):")
    hdr = f"  {'Date / Time':<18} {'Dir':<6} {'Sc':>4} {'Entry':>10} {'SL':>10} {'T1':>10} {'RR':>5}  T1 Result  T2 Result"
    print(hdr)
    print(f"  {'-'*80}")
    for r in results:
        t1_res = r["outcome"]
        t2_res = r.get("out_t2", "n/a")
        print(
            f"  {r['time']:<18} {r['direction']:<6} {r['score']:>4} "
            f"{r['entry']:>10.2f} {r['sl']:>10.2f} {r['tp']:>10.2f} "
            f"1:{r['rr']:>3.1f}  {t1_res:<10} {t2_res}"
        )

    summary = {
        "asset": asset, "total": len(results), "closed": n_closed,
        "wins": n_win, "losses": n_loss, "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2), "expectancy": round(expectancy, 2),
        "avg_rr": round(avg_rr, 1), "max_streak": max_streak,
        "trades": results,
    }
    return summary


# ═══════════════════════════════════════════════════════════════════
# SAVE RESULTS TO JSON  (for dashboard)
# ═══════════════════════════════════════════════════════════════════

RESULTS_FILE = "backtest_results.json"

def save_results(gold_data: list, btc_data: list, days: int):
    """Save backtest results to backtest_results.json for the dashboard."""
    import json
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).strftime("%d %b %Y  %H:%M IST")

    def _summary(results: list, asset: str) -> dict:
        closed = [r for r in results if r["outcome"] != "OPEN"]
        wins   = [r for r in closed  if r["outcome"] == "WIN"]
        losses = [r for r in closed  if r["outcome"] == "LOSS"]
        n_closed = len(closed)
        n_win    = len(wins)
        n_loss   = len(losses)
        win_rate = n_win / n_closed * 100 if n_closed else 0
        avg_rr   = float(sum(r["rr"] for r in results) / len(results)) if results else 0
        gross_profit = sum(r["rr"] for r in wins)
        gross_loss   = float(n_loss) or 1e-9
        pf           = gross_profit / gross_loss
        expectancy   = (win_rate / 100 * avg_rr) - (1 - win_rate / 100)
        streak = max_streak = 0
        for r in closed:
            if r["outcome"] == "LOSS":
                streak += 1; max_streak = max(max_streak, streak)
            else:
                streak = 0
        # score bracket breakdown
        brackets = []
        for lo, hi, lbl in [(60,74,"60-74"),(75,89,"75-89"),(90,150,"90+")]:
            grp   = [r for r in closed if lo <= r["score"] <= hi]
            g_win = [r for r in grp   if r["outcome"] == "WIN"]
            wr    = round(len(g_win)/len(grp)*100, 1) if grp else 0
            brackets.append({"label": lbl, "trades": len(grp), "win_rate": wr})
        return {
            "asset": asset, "total": len(results), "closed": n_closed,
            "wins": n_win, "losses": n_loss,
            "win_rate": round(win_rate, 1),
            "profit_factor": round(pf, 2),
            "expectancy": round(expectancy, 2),
            "avg_rr": round(avg_rr, 1),
            "max_streak": max_streak,
            "score_brackets": brackets,
            "trades": results,
        }

    payload = {
        "generated_at": now,
        "period_days":  days,
        "GOLD": _summary(gold_data, "GOLD"),
        "BTC":  _summary(btc_data,  "BTC"),
    }
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\n  Results saved to {RESULTS_FILE}")
    return payload


def load_backtest_results() -> dict:
    """Load saved backtest results (used by dashboard)."""
    import json
    try:
        with open(RESULTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[BACKTEST] load error: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="SMC/ICT Strategy Backtester")
    ap.add_argument("--asset", choices=["GOLD", "BTC", "ALL"],
                    default="ALL", help="Asset to backtest (default: ALL)")
    ap.add_argument("--days", type=int, default=50,
                    help="Days of history to use (max 58 for 15m resolution)")
    args = ap.parse_args()

    print(f"\n[BACKTEST] SMC / ICT Backtester   Asset: {args.asset}   Period: {args.days} days")

    gold_results = []
    btc_results  = []

    if args.asset in ("GOLD", "ALL"):
        gold_results = backtest_gold(args.days)
        print_report(gold_results, "GOLD")

    if args.asset in ("BTC", "ALL"):
        btc_results = backtest_btc(args.days)
        print_report(btc_results, "BTC")

    # Save combined results for dashboard
    if gold_results or btc_results:
        save_results(gold_results, btc_results, args.days)

    print(f"\n  Done!\n")


if __name__ == "__main__":
    main()
