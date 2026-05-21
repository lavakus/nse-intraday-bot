"""
Standalone scan script — runs on GitHub Actions (or any server).
Reads credentials from environment variables.
No desktop. Telegram only.
"""
import os, sys, time, requests
from datetime import datetime, timezone, timedelta

# ── CONFIG FROM ENV ────────────────────────────────────────────
TOKEN    = os.environ.get("TELEGRAM_TOKEN",   "8856759442:AAFLBXDVV9OESxbiKj-HRIOfeGFtSWqOdRM")
CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "8873804319")
THRESHOLD = float(os.environ.get("STRONG_SCORE", "9.0"))
BASE     = f"https://api.telegram.org/bot{TOKEN}"


# ── MARKET HOURS CHECK ─────────────────────────────────────────
def is_market_open() -> bool:
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    if ist.weekday() >= 5:          # Saturday / Sunday
        return False
    t = ist.hour * 100 + ist.minute
    return 915 <= t <= 1530


# ── TELEGRAM SEND ──────────────────────────────────────────────
def send(text: str):
    try:
        r = requests.post(f"{BASE}/sendMessage",
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
    action = "BUY" if sig["direction"] == "LONG" else "SELL"
    bar    = "#" * int(sig["score"]) + "." * (10 - int(sig["score"]))
    lines = [
        f"*** NSE INTRADAY ALERT ***",
        f"",
        f"Stock  : {sig['symbol']}",
        f"Action : {action}",
        f"Score  : {sig['score']}/10  [{bar}]",
        f"",
        f"Entry  : Rs {sig['entry']}",
        f"Target : Rs {sig['target']}",
        f"SL     : Rs {sig['sl']}",
        f"R:R    : 1:{sig['rr']}",
        f"",
        f"RSI    : {sig['rsi']}",
        f"VWAP   : Rs {sig['vwap']}",
        f"Volume : {sig['vol_ratio']}x average",
        f"",
        f"Signals:",
    ] + [f"  + {r}" for r in sig.get("reasons", [])] + [
        f"",
        f"Use SL strictly. Trade at your own risk.",
    ]
    return "\n".join(lines)


# ── MAIN SCAN ──────────────────────────────────────────────────
def main():
    print(f"NSE Scan starting — threshold={THRESHOLD}/10")

    if not is_market_open():
        ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        print(f"Market closed ({ist.strftime('%A %H:%M IST')}). Skipping scan.")
        sys.exit(0)

    # Import here so GitHub Actions only needs yfinance etc.
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
            sig = score_stock(df5, df15, sym, pdh, pdl)
            if sig and sig["score"] >= THRESHOLD:
                return sig
        except Exception:
            pass
        return None

    strong = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for sig in as_completed({pool.submit(scan_one, s): s for s in stocks}):
            result = sig.result()
            if result:
                strong.append(result)
                print(f"  STRONG: {result['symbol']} {result['direction']} score={result['score']}")

    strong.sort(key=lambda x: x["score"], reverse=True)
    print(f"\nResult: {len(strong)} strong signal(s)")

    # ── LOG SIGNALS TO JSON (persisted in repo via git commit) ────
    try:
        from signal_logger import log_signal, update_statuses
        update_statuses()          # refresh status of any already-open trades
        for s in strong[:10]:
            log_signal(s)
        print(f"[LOG] {len(strong)} signal(s) written to signals_log.json")
    except Exception as e:
        print(f"[LOG ERROR] {e}")

    if strong:
        send(f"NSE SCAN — {len(strong)} strong setup(s) found (score {THRESHOLD}+/10)")
        time.sleep(1)
        for s in strong[:10]:
            send(format_alert(s))
            time.sleep(0.5)
    else:
        print("No strong setups. No Telegram message sent.")


if __name__ == "__main__":
    main()
