"""
Unified entry point — runs NSE, Gold, and BTC bots concurrently
plus the Flask dashboard, all in a single process.

Usage:
  python run_all.py

Each asset runs in its own daemon thread.
The Flask dashboard is served on http://localhost:5000
"""
import threading
import os
import sys

def _start_nse():
    """NSE India bot (existing main.py logic)."""
    from main import market_watcher, run_chatbot
    threading.Thread(target=run_chatbot, daemon=True, name="NSE-chat").start()
    market_watcher()

def _start_gold():
    from run_gold import run_gold_watcher
    run_gold_watcher()

def _start_btc():
    from run_btc import run_btc_watcher
    run_btc_watcher()


if __name__ == "__main__":
    print("=" * 60)
    print("  UNIFIED TRADING BOT — NSE + GOLD + BTC")
    print("  Dashboard: http://localhost:5000")
    print("=" * 60)

    # Notify startup
    try:
        from notifier import telegram_send
        telegram_send(
            "Unified Bot started.\n\n"
            "Running: NSE India (SMC) | Gold (XAUUSD) | Bitcoin (BTC)\n\n"
            "NSE Kill Zones   : KZ1 09:15, KZ2 11:15, KZ3 13:30\n"
            "Gold Kill Zones  : KZ-A 05:30, KZ-L 13:30, KZ-NY 18:30\n"
            "BTC  Kill Zones  : KZ-A 05:30, KZ-L 13:30, KZ-NY 18:30\n\n"
            "Minimum score to alert: 65/150 (all assets)\n"
            "Dashboard: http://localhost:5000"
        )
    except Exception:
        pass

    # Launch all three asset watchers in daemon threads
    threads = [
        threading.Thread(target=_start_nse,  daemon=True, name="NSE"),
        threading.Thread(target=_start_gold, daemon=True, name="GOLD"),
        threading.Thread(target=_start_btc,  daemon=True, name="BTC"),
    ]
    for t in threads:
        t.start()
        print(f"  Started {t.name} watcher thread")

    # Start Flask dashboard in the main thread
    import dashboard
    port = int(os.environ.get("PORT", 5000))
    dashboard.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
