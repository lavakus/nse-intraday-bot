"""
Unified entry point — runs NSE, Gold, and BTC bots concurrently
plus the Flask dashboard, all in a single process.

Usage:
  python run_all.py
  (or double-click run_bot.bat on Windows)

Dashboard: http://localhost:5000
"""
import threading, os, sys, time

# ── IST time helper ───────────────────────────────────────────
from datetime import datetime, timezone, timedelta
def _now_ist():
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


# ── Thread targets ────────────────────────────────────────────

def _start_nse():
    """NSE intraday bot — ORB + VWAP + Breakout+Retest strategy."""
    try:
        from main import market_watcher, run_chatbot
        threading.Thread(target=run_chatbot, daemon=True, name="NSE-chat").start()
        market_watcher()
    except Exception as e:
        print(f"[NSE] Fatal error: {e}")


def _start_gold():
    """Gold (XAUUSD) bot — ICT+SMC 5-point confluence, threshold 120/150."""
    try:
        from run_gold import run_gold_watcher
        run_gold_watcher()
    except Exception as e:
        print(f"[GOLD] Fatal error: {e}")


def _start_btc():
    """Bitcoin (BTCUSDT) bot — SMC structure, threshold 65/150."""
    try:
        from run_btc import run_btc_watcher
        run_btc_watcher()
    except Exception as e:
        print(f"[BTC] Fatal error: {e}")


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    ist = _now_ist()
    print("=" * 62)
    print("  UNIFIED TRADING BOT  |  NSE + GOLD + BTC")
    print(f"  Started : {ist.strftime('%d %b %Y  %H:%M IST')}")
    print("  Dashboard: http://localhost:5000")
    print("=" * 62)
    print()
    print("  NSE   : ORB + VWAP Pullback + Breakout+Retest  (score 80+/150)")
    print("  GOLD  : ICT + SMC 5-point confluence            (score 120+/150)")
    print("  BTC   : SMC structure + ICT filters             (score 65+/150)")
    print()

    # ── Startup Telegram message ──────────────────────────────
    try:
        from notifier import telegram_send
        telegram_send(
            "Unified Trading Bot started.\n\n"
            "Running: NSE India | Gold (XAUUSD) | Bitcoin (BTC)\n\n"
            "NSE Strategy : ORB + VWAP + Breakout+Retest\n"
            "  KZ1 09:31-10:30 | KZ2 11:15-11:45 | KZ3 13:30-14:30\n"
            "  Min score : 80/150  |  Risk : 1% capital\n\n"
            "Gold Strategy : ICT + SMC (5-point confluence)\n"
            "  London KZ 13:30-16:30 | NY KZ 18:30-21:30 IST\n"
            "  Min score : 120/150\n\n"
            "BTC Strategy  : SMC + ICT filters\n"
            "  Min score : 65/150\n\n"
            "Dashboard: http://localhost:5000"
        )
        print("  [OK] Startup Telegram message sent")
    except Exception as e:
        print(f"  [WARN] Startup Telegram failed: {e}")

    # ── Launch all watchers as daemon threads ─────────────────
    threads = [
        threading.Thread(target=_start_nse,  daemon=True, name="NSE"),
        threading.Thread(target=_start_gold, daemon=True, name="GOLD"),
        threading.Thread(target=_start_btc,  daemon=True, name="BTC"),
    ]
    for t in threads:
        t.start()
        print(f"  [STARTED] {t.name} watcher thread")
        time.sleep(1)   # stagger startup to avoid API rate limits

    print()
    print("  All watchers running. Starting dashboard...")
    print("  Open http://localhost:5000 in your browser.")
    print()

    # ── Flask dashboard runs in main thread ───────────────────
    try:
        import dashboard
        port = int(os.environ.get("PORT", 5000))
        dashboard.app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
        )
    except Exception as e:
        print(f"[DASHBOARD] Error: {e}")
        print("Dashboard failed — bots still running in background threads.")
        # Keep main thread alive so daemon threads stay up
        while True:
            time.sleep(60)
