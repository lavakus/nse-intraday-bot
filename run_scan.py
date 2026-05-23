"""
Standalone scan script — runs on GitHub Actions (or any server).
Reads credentials from environment variables.
No desktop. Telegram only.
"""
import os, sys, time, requests
from datetime import datetime, timezone, timedelta

# ── CONFIG FROM ENV ────────────────────────────────────────────
TOKEN     = os.environ.get("TELEGRAM_TOKEN",   "8856759442:AAFLBXDVV9OESxbiKj-HRIOfeGFtSWqOdRM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "8873804319")
THRESHOLD = float(os.environ.get("STRONG_SCORE", "65"))
BASE      = f"https://api.telegram.org/bot{TOKEN}"


# ── MARKET HOURS CHECK ─────────────────────────────────────────

def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def is_market_open() -> bool:
    ist = _now_ist()
    if ist.weekday() >= 5:
        return False
    t = ist.hour * 100 + ist.minute
    return 915 <= t <= 1530


# ── TELEGRAM SEND ──────────────────────────────────────────────

def send(text: str):
    try:
        r  = requests.post(f"{BASE}/sendMessage",
                           json={"chat_id": CHAT_ID, "text": text},
                           timeout=10)
        ok = r.json().get("ok", False)
        if not ok:
            print(f"[TG ERROR] {r.json().get('description')}")
        return ok
    except Exception as e:
        print(f"[TG EXCEPTION] {e}")
        return False


def format_alert(sig: dict) -> str:
    action   = sig.get("signal", "BUY")
    score    = sig.get("score", 0)
    pct      = sig.get("score_pct", round(score / 150 * 100, 1))
    strength = sig.get("signal_strength", "GOOD")
    kz       = sig.get("kill_zone", "?")
    ph       = sig.get("phase_scores", {})
    tp       = sig.get("trade_params", {})
    entry    = tp.get("entry",    sig.get("entry", "?"))
    sl       = tp.get("sl",       sig.get("sl",    "?"))
    t1       = tp.get("t1",       sig.get("t1",    "?"))
    t2       = tp.get("t2",       sig.get("t2",    sig.get("target", "?")))
    rr       = tp.get("rr_ratio", sig.get("rr",    "?"))
    sl_pct   = tp.get("sl_pct",   "?")
    chk      = sig.get("must_have_checklist", {})
    bar      = "#" * int(score // 15) + "." * (10 - int(score // 15))

    lines = [
        f"*** NSE INTRADAY  —  {action} SIGNAL ***",
        f"",
        f"Stock     : {sig['symbol']}",
        f"Direction : {action}",
        f"Score     : {score}/150  ({pct}%)  [{bar}]",
        f"Strength  : {strength}",
        f"Kill Zone : {kz}",
        f"",
        f"--- TRADE PARAMETERS ---",
        f"Entry  : Rs {entry}",
        f"SL     : Rs {sl}  ({sl_pct}%)",
        f"T1     : Rs {t1}  (50% partial exit)",
        f"T2     : Rs {t2}  (full target)",
        f"R:R    : 1:{rr}",
        f"",
        f"--- PHASE SCORES ---",
        f"SMC Structure  : {ph.get('smc_structure', '?')}/60",
        f"ICT Time/Price : {ph.get('ict_time_price', '?')}/40",
        f"Price Action   : {ph.get('price_action', '?')}/27",
        f"Boosters       : {ph.get('boosters', '?')}/23",
        f"",
        f"--- CHECKLIST ---",
        f"{'OK' if chk.get('bos_or_choch_15min') else 'XX'}  BOS/CHOCH 15min",
        f"{'OK' if chk.get('order_block_valid')   else 'XX'}  Order Block",
        f"{'OK' if chk.get('liquidity_sweep')     else 'XX'}  Liquidity Sweep",
        f"{'OK' if chk.get('inside_kill_zone')    else 'XX'}  Kill Zone",
        f"",
        f"--- SIGNALS ---",
    ] + [f"  + {r}" for r in sig.get("reasons", [])] + [
        f"",
        f"RSI:{sig.get('rsi','?')}  VWAP:Rs{sig.get('vwap','?')}  Vol:{sig.get('vol_ratio','?')}x",
        f"",
        f"Move SL to breakeven at T1. Risk 0.5% of capital.",
        f"Trade at your own risk.",
    ]
    return "\n".join(lines)


# ── MAIN SCAN ──────────────────────────────────────────────────

def main():
    ist = _now_ist()
    print(f"NSE SMC Scan — threshold={THRESHOLD}/150  "
          f"time={ist.strftime('%H:%M IST %A')}")

    if not is_market_open():
        print(f"Market closed ({ist.strftime('%A %H:%M IST')}). Skipping scan.")
        sys.exit(0)

    from nse_stocks  import get_nse_stocks
    from data_fetcher import get_intraday_data, get_prev_day_high_low
    from strategy    import score_stock
    from concurrent.futures import ThreadPoolExecutor, as_completed

    stocks = get_nse_stocks()[:250]
    print(f"Scanning {len(stocks)} stocks...")

    def scan_one(sym):
        try:
            df5  = get_intraday_data(sym, "5m")
            df15 = get_intraday_data(sym, "15m")
            if df5.empty or df15.empty:
                return None
            pdh, pdl = get_prev_day_high_low(sym)
            sig = score_stock(df5, df15, sym, pdh, pdl, ist)
            if sig and sig.get("score", 0) >= THRESHOLD:
                return sig
        except Exception:
            pass
        return None

    strong = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for fut in as_completed({pool.submit(scan_one, s): s for s in stocks}):
            r = fut.result()
            if r:
                strong.append(r)
                print(f"  STRONG: {r['symbol']} {r['signal']} "
                      f"score={r['score']}/150 [{r['signal_strength']}]")

    strong.sort(key=lambda x: x["score"], reverse=True)
    print(f"\nResult: {len(strong)} strong signal(s)")

    # ── Log signals to signals_log.json ───────────────────────
    try:
        from signal_logger import log_signal, update_statuses
        update_statuses()          # refresh open trade statuses
        for s in strong[:10]:
            log_signal(s)
        print(f"[LOG] {len(strong[:10])} signal(s) written to signals_log.json")
    except Exception as e:
        print(f"[LOG ERROR] {e}")

    # ── Send to Telegram ───────────────────────────────────────
    if strong:
        send(f"NSE SMC SCAN — {len(strong)} strong setup(s) found "
             f"(score {THRESHOLD}+/150)")
        time.sleep(1)
        for s in strong[:5]:       # cap at 5 alerts per scan
            send(format_alert(s))
            time.sleep(0.5)
    else:
        print("No strong setups in this kill zone. No Telegram message sent.")


if __name__ == "__main__":
    main()
