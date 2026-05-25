"""
Swing Stock Scanner + Daily Tracker — NSE India (5-day Mon–Fri holds)
=====================================================================
Monday  → scan full watchlist, pick top 7, send Telegram alert
Tue–Fri → fetch live prices, update P&L, check target/SL hit, send EOD update

GitHub Actions runs this file every market day at 15:35 IST (10:05 UTC).
On Monday it scans for new picks. On other days it just updates statuses.

Local usage:
  python run_swing.py            # auto-detects day
  FORCE_SWING=1 python run_swing.py   # force full scan (any day)
  UPDATE_ONLY=1 python run_swing.py   # force status update only
"""

import os, json, time
from datetime import datetime, timezone, timedelta, date

import yfinance as yf
import pandas as pd

from swing_strategy import score_swing, SWING_WATCHLIST
from notifier       import telegram_send

SWING_LOG = "swing_log.json"
TOP_N     = 7
MIN_SCORE = 55

# GitHub raw fallback so the dashboard (on Render / remote) can read the log
# even when the local file doesn't exist (bot runs on GitHub Actions)
_SWING_LOG_URL = os.environ.get(
    "SWING_LOG_URL",
    "https://raw.githubusercontent.com/lavakus/nse-intraday-bot/main/swing_log.json"
)


# ── Time helpers ─────────────────────────────────────────────────

def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))

def _week_key(dt: datetime = None) -> str:
    d = (dt or _now_ist()).date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"

def _today_str() -> str:
    return _now_ist().strftime("%Y-%m-%d")


# ── Log helpers ───────────────────────────────────────────────────

def _load_log() -> list:
    # 1) Try local file first
    try:
        with open(SWING_LOG, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[SWING] Failed to load local log: {e}")

    # 2) Fallback: fetch from GitHub (for Render / remote dashboard)
    try:
        import requests as _req
        r = _req.get(_SWING_LOG_URL, timeout=10)
        if r.status_code == 200:
            print("[SWING] Loaded log from GitHub fallback")
            return r.json()
    except Exception as e:
        print(f"[SWING] GitHub fallback failed: {e}")
    return []

def _save_log(data: list):
    with open(SWING_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ── Live price fetch ──────────────────────────────────────────────

def _fetch_live(symbol: str) -> float | None:
    try:
        tk = yf.Ticker(f"{symbol}.NS")
        return float(tk.fast_info["last_price"])
    except Exception:
        return None

def _fetch_daily(symbol: str) -> pd.DataFrame | None:
    try:
        tk = yf.Ticker(f"{symbol}.NS")
        df = tk.history(period="18mo", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df[["open","high","low","close","volume"]].dropna()
    except Exception:
        return None


# ── Progress calculator ───────────────────────────────────────────

def _calc_progress(rec: dict, price: float) -> dict:
    """
    For a live price, calculate how far the trade has moved
    toward target and away from SL.
    Returns progress_pct (0–100 toward T2) and day_pnl_pct.
    """
    entry = float(rec.get("entry", price))
    t2    = float(rec.get("t2", price))
    sl    = float(rec.get("sl", price))
    total_move = t2 - entry
    done_move  = price - entry
    progress   = round(done_move / total_move * 100, 1) if total_move > 0 else 0

    # Distance to SL and T2 in %
    dist_sl = round((price - sl) / price * 100, 2)
    dist_t2 = round((t2 - price) / price * 100, 2)

    return {
        "progress_pct": max(min(progress, 100), -50),
        "dist_sl_pct":  dist_sl,
        "dist_t2_pct":  dist_t2,
    }


# ── Status updater ────────────────────────────────────────────────

def update_swing_statuses(silent: bool = False) -> list:
    """
    Fetch live prices for every OPEN swing pick.
    Updates: current_price, pnl_pct, pnl_pts, progress_pct,
             dist_sl_pct, dist_t2_pct, last_updated.
    Marks TARGET HIT / SL HIT when crossed.
    Returns updated data list.
    """
    data    = _load_log()
    changed = 0

    open_picks = [r for r in data if r.get("status") == "OPEN"]
    if not open_picks:
        return data

    if not silent:
        print(f"[SWING] Updating {len(open_picks)} open positions…")

    for rec in open_picks:
        price = _fetch_live(rec["symbol"])
        if price is None:
            continue

        entry = float(rec["entry"])
        t1    = float(rec.get("t1", rec["entry"]))
        t2    = float(rec["t2"])
        sl    = float(rec["sl"])

        prog = _calc_progress(rec, price)

        rec["current_price"]  = price
        rec["exit_price"]     = price          # compat alias
        rec["pnl_pct"]        = round((price - entry) / entry * 100, 2)
        rec["pnl_pts"]        = round(price - entry, 2)
        rec["progress_pct"]   = prog["progress_pct"]
        rec["dist_sl_pct"]    = prog["dist_sl_pct"]
        rec["dist_t2_pct"]    = prog["dist_t2_pct"]
        rec["t1_hit"]         = price >= t1
        rec["last_updated"]   = _now_ist().strftime("%Y-%m-%d %H:%M IST")

        if price >= t2:
            rec["status"]     = "TARGET HIT"
            rec["exit_price"] = price
            if not silent:
                print(f"  ✓ {rec['symbol']} TARGET HIT @ ₹{price}  (+{rec['pnl_pct']}%)")
            changed += 1
        elif price <= sl:
            rec["status"]     = "SL HIT"
            rec["exit_price"] = price
            if not silent:
                print(f"  ✗ {rec['symbol']} SL HIT @ ₹{price}  ({rec['pnl_pct']}%)")
            changed += 1
        else:
            arrow = "▲" if rec["pnl_pct"] >= 0 else "▼"
            if not silent:
                print(f"  {arrow} {rec['symbol']:<14} ₹{price:<10} "
                      f"P&L {rec['pnl_pct']:+.2f}%  "
                      f"→T2 {rec['dist_t2_pct']:.1f}%  SL buffer {rec['dist_sl_pct']:.1f}%")

    _save_log(data)       # always save (prices updated)
    return data


# ── EOD Telegram update ───────────────────────────────────────────

def send_eod_update():
    """Send daily EOD update of all open swing positions."""
    data  = _load_log()
    week  = _week_key()
    open_ = [r for r in data if r.get("status") == "OPEN" and r.get("week") == week]
    hits  = [r for r in data if r.get("status") == "TARGET HIT" and r.get("week") == week]
    sls   = [r for r in data if r.get("status") == "SL HIT"    and r.get("week") == week]

    if not (open_ or hits or sls):
        return

    ist   = _now_ist()
    lines = [
        f"📊 SWING EOD UPDATE — {ist.strftime('%A %d %b')}  {week}",
        f"",
    ]

    if open_:
        lines.append("── Open Positions ──")
        for r in open_:
            pnl  = r.get("pnl_pct", 0) or 0
            prog = r.get("progress_pct", 0) or 0
            bar  = "█" * max(0, int(prog / 10)) + "░" * max(0, 10 - int(prog / 10))
            arrow = "▲" if pnl >= 0 else "▼"
            lines.append(
                f"{arrow} {r['symbol']:<14}  ₹{r.get('current_price','?'):<10}"
                f"  P&L {pnl:+.2f}%  [{bar}] {prog:.0f}% to T2"
            )
            lines.append(
                f"   Entry ₹{r['entry']}  |  T2 ₹{r['t2']}  |  SL ₹{r['sl']}"
            )

    if hits:
        lines.append("")
        lines.append("✅ Target Hit Today")
        for r in hits:
            lines.append(f"  ✓ {r['symbol']}  +{r.get('pnl_pct',0):.2f}%  @ ₹{r.get('exit_price','?')}")

    if sls:
        lines.append("")
        lines.append("❌ SL Hit Today")
        for r in sls:
            lines.append(f"  ✗ {r['symbol']}  {r.get('pnl_pct',0):.2f}%  @ ₹{r.get('exit_price','?')}")

    lines += ["", "⚠ Exit all positions by Friday 15:20 IST."]
    telegram_send("\n".join(lines))


# ── Full week scanner (Monday) ────────────────────────────────────

def scan_swing() -> list:
    """Score all watchlist stocks and return top picks sorted by score."""
    ist  = _now_ist()
    week = _week_key()
    print(f"[SWING] Full scan — {ist.strftime('%A %d %b %Y')}  {week}")
    print(f"[SWING] Scanning {len(SWING_WATCHLIST)} stocks…")

    results = []
    for i, sym in enumerate(SWING_WATCHLIST, 1):
        print(f"  [{i:>2}/{len(SWING_WATCHLIST)}] {sym:<18}", end=" ", flush=True)
        df = _fetch_daily(sym)
        if df is None:
            print("no data"); continue

        sig = score_swing(sym, df)
        if sig and sig.get("score", 0) >= MIN_SCORE:
            price = _fetch_live(sym) or sig["entry"]
            sig["week"]          = week
            sig["scan_date"]     = ist.strftime("%Y-%m-%d")
            sig["status"]        = "OPEN"
            sig["current_price"] = price
            sig["exit_price"]    = price
            sig["pnl_pct"]       = round((price - sig["entry"]) / sig["entry"] * 100, 2)
            sig["pnl_pts"]       = round(price - sig["entry"], 2)
            sig["progress_pct"]  = _calc_progress(sig, price)["progress_pct"]
            sig["dist_sl_pct"]   = _calc_progress(sig, price)["dist_sl_pct"]
            sig["dist_t2_pct"]   = _calc_progress(sig, price)["dist_t2_pct"]
            sig["t1_hit"]        = False
            sig["last_updated"]  = ist.strftime("%Y-%m-%d %H:%M IST")
            results.append(sig)
            print(f"✓ score={sig['score']}/100 [{sig['signal_strength']}] "
                  f"entry=₹{sig['entry']}  T2=₹{sig['t2']}  SL=₹{sig['sl']}")
        else:
            print(f"score={sig.get('score',0) if sig else 0} — skip")

        time.sleep(0.3)

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:TOP_N]
    print(f"\n[SWING] {len(results)} qualify → Top {len(top)} selected")

    # Auto-assign rank IDs
    for rank, p in enumerate(top, 1):
        p["id"]   = rank
        p["rank"] = rank

    return top


def _format_monday_alert(picks: list) -> str:
    ist  = _now_ist()
    week = _week_key()
    lines = [
        f"📈 WEEKLY SWING PICKS — {week}",
        f"📅 {ist.strftime('%A %d %b %Y')}  |  Hold: Mon→Fri (5 days)",
        f"🎯 Strategy: EMA Trend + RSI + Volume Breakout  |  Min score 55/100",
        f"",
        f"{'Rk':<3} {'Symbol':<13} {'Sc':>4} {'Entry':>8} {'T1':>8} {'T2':>9} {'SL':>8} {'R:R':>5}",
        "─" * 60,
    ]
    for rank, p in enumerate(picks, 1):
        lines.append(
            f"#{rank:<2} {p['symbol']:<13} {p['score']:>3}/100 "
            f"₹{p['entry']:>7} ₹{p['t1']:>7} ₹{p['t2']:>8} ₹{p['sl']:>7} 1:{p['rr_t2']}"
        )

    if picks:
        p = picks[0]
        lines += [
            f"",
            f"★ TOP PICK: {p['symbol']}  [{p['signal_strength']}]  Score {p['score']}/100",
            f"  Entry : ₹{p['entry']}",
            f"  T1    : ₹{p['t1']}  (R:R 1:{p['rr_t1']}) — book 50% here",
            f"  T2    : ₹{p['t2']}  (R:R 1:{p['rr_t2']}) — full exit or Fri close",
            f"  SL    : ₹{p['sl']}  (-{p['sl_pct']}%) — strict stop",
            f"  RSI {p['rsi']} | Vol {p['vol_ratio']}× | MACD {'✅' if p['macd_bullish'] else '❌'}",
            f"  Why: {' · '.join(p['reasons'][:3])}",
        ]

    lines += [
        "", "⚠ Max 1–2% capital risk per trade. Exit ALL by Fri 15:20 IST.",
        "You will get an EOD update every day this week.",
    ]
    return "\n".join(lines)


# ── Dashboard data provider ───────────────────────────────────────

def get_swing_data() -> dict:
    """
    Load swing log, refresh live prices for OPEN picks, return dashboard dict.
    This is called on every dashboard page load.
    """
    data = update_swing_statuses(silent=True)
    week = _week_key()

    week_picks = [r for r in data if r.get("week") == week]
    wins       = [r for r in data if r.get("status") == "TARGET HIT"]
    losses     = [r for r in data if r.get("status") == "SL HIT"]
    open_      = [r for r in data if r.get("status") == "OPEN"]
    closed     = len(wins) + len(losses)

    summary = {
        "total":     len(data),
        "wins":      len(wins),
        "losses":    len(losses),
        "open":      len(open_),
        "win_rate":  round(len(wins) / closed * 100, 1) if closed > 0 else 0,
        "avg_score": round(sum(r.get("score", 0) for r in data) / len(data), 1) if data else 0,
        "week":      week,
    }
    return {
        "week_picks":  week_picks,
        "all_picks":   list(reversed(data))[:40],
        "summary":     summary,
    }


# ── Entry point ───────────────────────────────────────────────────

def main():
    ist     = _now_ist()
    week    = _week_key()
    weekday = ist.weekday()   # 0=Mon … 4=Fri

    force_scan   = os.environ.get("FORCE_SWING",  "0") == "1"
    update_only  = os.environ.get("UPDATE_ONLY",  "0") == "1"

    print(f"[SWING] {ist.strftime('%A %d %b %Y %H:%M IST')}  {week}")

    # ── Daily status update (runs every market day) ───────────────
    updated_data = update_swing_statuses()
    open_count   = sum(1 for r in updated_data if r.get("status") == "OPEN")
    print(f"[SWING] {open_count} open positions after update")

    # ── Send EOD Telegram update (Tue–Fri, or any day if update_only) ──
    if update_only or (weekday > 0):          # not Monday
        send_eod_update()
        if not force_scan:
            return

    # ── Monday: full scan for new picks ──────────────────────────
    if weekday == 0 or force_scan:
        existing = _load_log()
        if any(r.get("week") == week for r in existing) and not force_scan:
            print(f"[SWING] Already scanned {week}. Use FORCE_SWING=1 to re-scan.")
            return

        picks = scan_swing()
        if not picks:
            print("[SWING] No qualifying stocks this week")
            telegram_send(
                f"📊 Swing Scan {week}: No qualifying stocks found.\n"
                f"Market may be in a correction — no swing trades this week."
            )
            return

        existing.extend(picks)
        _save_log(existing)
        print(f"[SWING] Saved {len(picks)} picks for {week}")

        ok = telegram_send(_format_monday_alert(picks))
        print(f"[SWING] Monday alert: {'SENT' if ok else 'FAILED'}")

        print("\n── This week's picks ──")
        for p in picks:
            print(f"  #{p['rank']} {p['symbol']:<14} score={p['score']}/100  "
                  f"entry=₹{p['entry']}  T2=₹{p['t2']}  SL=₹{p['sl']}")


if __name__ == "__main__":
    main()
