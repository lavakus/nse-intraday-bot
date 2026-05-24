"""
Swing Stock Scanner — NSE India (5-day Mon–Fri holds)
=====================================================
Scans the full NIFTY 50 + select midcap watchlist every Monday.
Picks the TOP 7 stocks by score, saves to swing_log.json.
Sends Telegram alert with the week's picks.

Run via GitHub Actions every Monday 09:15 IST (03:45 UTC).
Or locally:  python run_swing.py
"""

import os, json, time
from datetime import datetime, timezone, timedelta, date

import yfinance as yf
import pandas as pd

from swing_strategy  import score_swing, SWING_WATCHLIST
from notifier        import telegram_send

SWING_LOG   = "swing_log.json"
TOP_N       = 7          # number of picks per week
MIN_SCORE   = 55


# ── Helpers ──────────────────────────────────────────────────────

def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _week_key() -> str:
    """ISO week string e.g. '2025-W22'"""
    d = _now_ist().date()
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def _load_log() -> list:
    try:
        with open(SWING_LOG) as f:
            return json.load(f)
    except Exception:
        return []


def _save_log(data: list):
    with open(SWING_LOG, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _fetch_daily(symbol: str) -> pd.DataFrame | None:
    """Fetch 1.5 years of daily data for the symbol."""
    try:
        tk = yf.Ticker(f"{symbol}.NS")
        df = tk.history(period="18mo", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        return df
    except Exception:
        return None


# ── Scanner ───────────────────────────────────────────────────────

def scan_swing() -> list:
    """
    Score all watchlist stocks and return top picks sorted by score.
    Returns list of signal dicts.
    """
    ist  = _now_ist()
    week = _week_key()
    print(f"[SWING] Scanning {len(SWING_WATCHLIST)} stocks — {ist.strftime('%A %d %b %Y')}  Week {week}")

    results = []
    for i, sym in enumerate(SWING_WATCHLIST, 1):
        print(f"  [{i:>2}/{len(SWING_WATCHLIST)}] {sym:<18}", end=" ", flush=True)
        df = _fetch_daily(sym)
        if df is None:
            print("no data")
            continue

        sig = score_swing(sym, df)
        if sig and sig.get("score", 0) >= MIN_SCORE:
            sig["week"]     = week
            sig["scan_date"] = ist.strftime("%Y-%m-%d")
            sig["status"]   = "OPEN"
            sig["exit_price"] = None
            sig["pnl_pct"]  = None
            sig["id"]       = i
            results.append(sig)
            print(f"SCORE={sig['score']}/100  [{sig['signal_strength']}]  "
                  f"entry={sig['entry']}  T2={sig['t2']}  SL={sig['sl']}")
        else:
            print(f"score={sig.get('score',0) if sig else 0} — skip")

        time.sleep(0.3)   # gentle rate limit

    # Sort by score descending, take top N
    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:TOP_N]
    print(f"\n[SWING] {len(results)} qualifying stocks → Top {len(top)} selected")
    return top


# ── Telegram alert ────────────────────────────────────────────────

def _format_swing_alert(picks: list) -> str:
    ist  = _now_ist()
    week = _week_key()
    lines = [
        f"📈 WEEKLY SWING PICKS — {week}",
        f"Scan date : {ist.strftime('%A %d %b %Y')}",
        f"Hold      : Mon open → Fri close (5 days)",
        f"Strategy  : EMA Trend + RSI + Volume Breakout",
        f"",
        f"{'Rank':<4} {'Symbol':<14} {'Score':<8} {'Entry':<10} {'T1':<10} {'T2':<10} {'SL':<10} {'R:R'}",
        "─" * 72,
    ]
    for rank, p in enumerate(picks, 1):
        lines.append(
            f"#{rank:<3} {p['symbol']:<14} {p['score']}/100   "
            f"₹{p['entry']:<9} ₹{p['t1']:<9} ₹{p['t2']:<9} ₹{p['sl']:<9} 1:{p['rr_t2']}"
        )

    lines += ["", "── Top Pick Detail ──"]
    if picks:
        p = picks[0]
        lines += [
            f"",
            f"★ {p['symbol']}  [{p['signal_strength']}]  Score {p['score']}/100",
            f"  Entry : ₹{p['entry']}",
            f"  SL    : ₹{p['sl']}  (-{p['sl_pct']}%)",
            f"  T1    : ₹{p['t1']}  (R:R 1:{p['rr_t1']})",
            f"  T2    : ₹{p['t2']}  (R:R 1:{p['rr_t2']})",
            f"  RSI   : {p['rsi']}  |  Vol: {p['vol_ratio']}×  |  MACD: {'✅' if p['macd_bullish'] else '❌'}",
            f"  Why   : {' · '.join(p['reasons'][:3])}",
        ]

    lines += [
        "",
        "⚠ Risk max 1–2% capital per trade. Exit all by Friday close.",
        "These are swing setups, not intraday signals.",
    ]
    return "\n".join(lines)


# ── Status updater ────────────────────────────────────────────────

def update_swing_statuses() -> list:
    """Update OPEN swing picks with current price and P&L."""
    data    = _load_log()
    changed = 0

    for rec in data:
        if rec.get("status") != "OPEN":
            continue
        try:
            tk    = yf.Ticker(f"{rec['symbol']}.NS")
            price = float(tk.fast_info["last_price"])
            entry = float(rec["entry"])
            t2    = float(rec["t2"])
            sl    = float(rec["sl"])
            rec["exit_price"] = price
            rec["pnl_pct"]    = round((price - entry) / entry * 100, 2)

            if price >= t2:
                rec["status"] = "TARGET HIT"
                changed += 1
            elif price <= sl:
                rec["status"] = "SL HIT"
                changed += 1
        except Exception:
            pass

    if changed:
        _save_log(data)
    return data


def get_swing_data() -> dict:
    """
    Return {week_picks, all_history, summary} for the dashboard.
    """
    data    = update_swing_statuses()
    week    = _week_key()

    # Current week picks
    week_picks = [r for r in data if r.get("week") == week]

    # All historical picks
    wins   = [r for r in data if r.get("status") == "TARGET HIT"]
    losses = [r for r in data if r.get("status") == "SL HIT"]
    open_  = [r for r in data if r.get("status") == "OPEN"]
    closed = len(wins) + len(losses)

    summary = {
        "total":    len(data),
        "wins":     len(wins),
        "losses":   len(losses),
        "open":     len(open_),
        "win_rate": round(len(wins) / closed * 100, 1) if closed > 0 else 0,
        "avg_score": round(sum(r.get("score", 0) for r in data) / len(data), 1) if data else 0,
        "week":     week,
    }
    return {
        "week_picks":   week_picks,
        "all_picks":    list(reversed(data))[:30],
        "summary":      summary,
    }


# ── Main ─────────────────────────────────────────────────────────

def main():
    ist  = _now_ist()
    week = _week_key()
    print(f"[SWING] Weekly scan — {ist.strftime('%A %d %b %Y')}  {week}")

    # Skip if not Monday (or if running as forced via env)
    forced = os.environ.get("FORCE_SWING", "0") == "1"
    if ist.weekday() != 0 and not forced:
        print("[SWING] Not Monday — skipping scan. Set FORCE_SWING=1 to override.")
        return

    # Check if already scanned this week
    existing = _load_log()
    if any(r.get("week") == week for r in existing) and not forced:
        print(f"[SWING] Already scanned for {week}. Set FORCE_SWING=1 to re-scan.")
        return

    picks = scan_swing()
    if not picks:
        print("[SWING] No qualifying stocks this week")
        telegram_send(f"📊 Swing Scan {week}: No qualifying stocks found this week. "
                      f"Market may be choppy — no swing trades recommended.")
        return

    # Append to log (preserve history)
    existing.extend(picks)
    _save_log(existing)
    print(f"[SWING] Saved {len(picks)} picks to {SWING_LOG}")

    # Send Telegram alert
    msg = _format_swing_alert(picks)
    ok  = telegram_send(msg)
    print(f"[SWING] Telegram: {'SENT' if ok else 'FAILED'}")
    print("\n── This week's picks ──")
    for p in picks:
        print(f"  {p['symbol']:<16} score={p['score']}/100  entry={p['entry']}  T2={p['t2']}  SL={p['sl']}")


if __name__ == "__main__":
    main()
