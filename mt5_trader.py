"""
MT5 Auto-Trader — Gold (XAUUSD) + Bitcoin (BTCUSD)
====================================================
Polls GitHub signals every 30 sec.
New signal → places order on your MT5 DEMO account instantly.
Monitors SL/TP → closes trade + sends Telegram confirmation.

SETUP (one-time):
  1. Open FREE demo at: https://www.xm.com/  (or IC Markets / Exness)
  2. Download MetaTrader 5 terminal from your broker
  3. Log in with demo credentials
  4. pip install MetaTrader5 requests
  5. Create a file called mt5_config.json (see bottom of this file)
  6. Run: python mt5_trader.py

IMPORTANT: MT5 terminal must be OPEN and LOGGED IN while this runs.
           This script must run on Windows (MT5 only works on Windows).
"""

import os, json, time, math, sys
from datetime import datetime, timezone, timedelta
import requests

# ── MT5 Import ────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
except ImportError:
    print("=" * 60)
    print("  MetaTrader5 package not found!")
    print("  Run:  pip install MetaTrader5")
    print("=" * 60)
    sys.exit(1)

# ── Load Config ───────────────────────────────────────────────────
CONFIG_FILE = "mt5_config.json"

def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    # Fallback to env vars
    return {
        "login":    int(os.environ.get("MT5_LOGIN",    "0")),
        "password": os.environ.get("MT5_PASSWORD", ""),
        "server":   os.environ.get("MT5_SERVER",   ""),
        "path":     os.environ.get("MT5_PATH",     ""),
        "risk_pct": float(os.environ.get("MT5_RISK_PCT", "1.0")),
        "telegram_token":   os.environ.get("TELEGRAM_TOKEN",   ""),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "github_user": "lavakus",
        "github_repo": "nse-intraday-bot",
        "assets":   ["GOLD", "BTC"],
        "max_positions_per_asset": 1,
    }

CFG = _load_config()

# ── Symbol map  (our name → your broker's MT5 symbol) ─────────────
# XM.com uses XAUUSD and BTCUSD — adjust if your broker differs
SYMBOL_MAP = {
    "GOLD":    CFG.get("symbol_gold",   "XAUUSD"),
    "XAUUSD":  CFG.get("symbol_gold",   "XAUUSD"),
    "BTC":     CFG.get("symbol_btc",    "BTCUSD"),
    "BTCUSDT": CFG.get("symbol_btc",    "BTCUSD"),
}

GITHUB_BASE = (
    f"https://raw.githubusercontent.com/"
    f"{CFG.get('github_user','lavakus')}/"
    f"{CFG.get('github_repo','nse-intraday-bot')}/main"
)
SIGNAL_URLS = {
    "GOLD": f"{GITHUB_BASE}/gold_signals_log.json",
    "BTC":  f"{GITHUB_BASE}/btc_signals_log.json",
}

POLL_SEC   = 30    # check GitHub every 30 seconds
MAGIC      = 20250101   # magic number to identify our bot's trades


# ═══════════════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════════════

def tg(text: str):
    token   = CFG.get("telegram_token",   "")
    chat_id = CFG.get("telegram_chat_id", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        print(f"[TG] {e}")


# ═══════════════════════════════════════════════════════════════════
# MT5 CONNECTION
# ═══════════════════════════════════════════════════════════════════

def connect() -> bool:
    """Connect to MT5 terminal. Returns True if successful.

    Strategy:
      1) ATTACH to an already-running, logged-in terminal (no password
         needed — recommended; just log in once inside MT5 and keep it open).
      2) Fall back to logging in with the credentials in mt5_config.json.
    """
    path = CFG.get("path") or None

    # ── 1) Attach to a running, logged-in terminal (no creds) ────────
    if mt5.initialize(**({"path": path} if path else {})):
        if mt5.account_info() is not None:
            print("[MT5] Attached to running terminal (manual login).")
        else:
            mt5.shutdown()   # terminal up but no account — try explicit login
    # ── 2) Fall back to explicit login with stored credentials ───────
    if mt5.account_info() is None:
        kwargs = {}
        if path:
            kwargs["path"] = path
        if CFG.get("login"):
            kwargs["login"]    = int(CFG["login"])
            kwargs["password"] = CFG["password"]
            kwargs["server"]   = CFG["server"]
        if not mt5.initialize(**kwargs):
            print(f"[MT5] Initialize failed: {mt5.last_error()}")
            print( "[MT5] TIP: open MetaTrader 5, log in to your XM demo "
                   "account, enable Algo Trading, and keep it open.")
            return False

    info = mt5.account_info()
    if info is None:
        print(f"[MT5] Account info failed: {mt5.last_error()}")
        print( "[MT5] TIP: log in inside the MT5 terminal first, then re-run.")
        return False

    print(f"[MT5] Connected — Account #{info.login}  "
          f"Balance: {info.balance:.2f} {info.currency}  "
          f"Server: {info.server}")
    tg(f"🤖 MT5 Auto-Trader STARTED\n"
       f"Account: #{info.login} (DEMO)\n"
       f"Balance: {info.balance:.2f} {info.currency}\n"
       f"Watching: {', '.join(CFG.get('assets', ['GOLD','BTC']))}\n"
       f"Risk per trade: {CFG.get('risk_pct', 1.0)}% of balance")
    return True


def get_balance() -> float:
    info = mt5.account_info()
    return info.balance if info else 0.0


# ═══════════════════════════════════════════════════════════════════
# LOT SIZE CALCULATOR
# ═══════════════════════════════════════════════════════════════════

def calc_lot(symbol: str, entry: float, sl: float) -> float:
    """
    Risk-based lot size.
    Lot = (account_balance * risk_pct) / (sl_distance * tick_val_per_lot)
    """
    sym_info = mt5.symbol_info(symbol)
    if sym_info is None:
        print(f"[LOT] Symbol {symbol} not found")
        return sym_info

    balance      = get_balance()
    risk_amount  = balance * (CFG.get("risk_pct", 1.0) / 100.0)
    sl_distance  = abs(entry - sl)

    if sl_distance <= 0:
        print(f"[LOT] SL distance is zero for {symbol}")
        return sym_info.volume_min

    # Value of 1 pip per 1 lot = tick_value / tick_size
    tick_size    = sym_info.trade_tick_size
    tick_value   = sym_info.trade_tick_value
    if tick_size <= 0:
        return sym_info.volume_min

    val_per_pip_per_lot = tick_value / tick_size   # USD per price-unit per lot
    lot = risk_amount / (sl_distance * val_per_pip_per_lot)

    # Snap to broker's step
    step = sym_info.volume_step
    lot  = math.floor(lot / step) * step
    lot  = max(sym_info.volume_min, min(lot, sym_info.volume_max))
    lot  = round(lot, 2)

    print(f"[LOT] {symbol}  balance={balance:.2f}  risk={risk_amount:.2f}  "
          f"sl_dist={sl_distance:.4f}  lot={lot}")
    return lot


# ═══════════════════════════════════════════════════════════════════
# ORDER PLACEMENT
# ═══════════════════════════════════════════════════════════════════

def place_order(signal: dict) -> bool:
    """
    Places a market order based on signal dict from our bot.
    Returns True if order placed successfully.
    """
    asset     = signal.get("asset", signal.get("symbol", "GOLD"))
    symbol    = SYMBOL_MAP.get(asset.upper(), asset)
    direction = signal.get("direction", "LONG")
    tp        = signal.get("trade_params", {})

    entry_price = float(tp.get("entry", signal.get("entry", 0)))
    sl_price    = float(tp.get("sl",    signal.get("sl",    0)))
    t2_price    = float(tp.get("t2",    signal.get("target", 0)))
    score       = signal.get("score", 0)
    sig_id      = signal.get("id", "?")

    if not entry_price or not sl_price or not t2_price:
        print(f"[ORDER] Missing price levels for signal #{sig_id}")
        return False

    # Enable symbol trading
    if not mt5.symbol_select(symbol, True):
        print(f"[ORDER] Cannot select symbol {symbol}")
        return False

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"[ORDER] Cannot get tick for {symbol}")
        return False

    order_type = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
    price      = tick.ask if direction == "LONG" else tick.bid
    lot        = calc_lot(symbol, price, sl_price)

    if lot is None or lot <= 0:
        print(f"[ORDER] Invalid lot size for {symbol}")
        return False

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           round(sl_price,    5),
        "tp":           round(t2_price,    5),
        "deviation":    20,          # max slippage in points
        "magic":        MAGIC,
        "comment":      f"BOT#{sig_id} score={score}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None:
        print(f"[ORDER] order_send returned None: {mt5.last_error()}")
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = (
            f"✅ TRADE EXECUTED — {symbol} {'🟢 BUY' if direction=='LONG' else '🔴 SELL'}\n"
            f"Signal #{sig_id}  Score: {score}/150\n"
            f"Entry : {price:.4f}\n"
            f"SL    : {sl_price:.4f}\n"
            f"TP    : {t2_price:.4f}\n"
            f"Lots  : {lot}\n"
            f"Order : #{result.order}"
        )
        print(f"[ORDER] ✅ {symbol} {direction}  lot={lot}  order=#{result.order}")
        tg(msg)
        return True
    else:
        err = (
            f"❌ TRADE FAILED — {symbol}\n"
            f"Error: {result.retcode} — {result.comment}"
        )
        print(f"[ORDER] ❌ Failed retcode={result.retcode}  comment={result.comment}")
        tg(err)
        return False


# ═══════════════════════════════════════════════════════════════════
# POSITION MONITOR
# ═══════════════════════════════════════════════════════════════════

def count_open_positions(symbol: str) -> int:
    positions = mt5.positions_get(symbol=symbol)
    return len(positions) if positions else 0


def report_closed_trades():
    """
    Check recently closed deals and notify Telegram.
    Runs every poll cycle.
    """
    hist = mt5.history_deals_get(
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
        datetime.now(timezone.utc)
    )
    if hist is None:
        return

    for deal in hist:
        if deal.magic != MAGIC:
            continue
        if deal.entry != mt5.DEAL_ENTRY_OUT:   # only closed deals
            continue
        profit = deal.profit
        symbol = deal.symbol
        emoji  = "✅" if profit >= 0 else "❌"
        _notify_closed_key = f"{deal.ticket}"
        if _notify_closed_key in _already_reported:
            continue
        _already_reported.add(_notify_closed_key)

        msg = (
            f"{emoji} TRADE CLOSED — {symbol}\n"
            f"Profit: {'+'if profit>=0 else ''}{profit:.2f} USD\n"
            f"Ticket: #{deal.ticket}"
        )
        tg(msg)
        print(f"[CLOSED] {symbol}  profit={profit:.2f}  ticket={deal.ticket}")

_already_reported: set = set()


# ═══════════════════════════════════════════════════════════════════
# SIGNAL FETCHER
# ═══════════════════════════════════════════════════════════════════

def fetch_signals(asset: str) -> list:
    url = SIGNAL_URLS.get(asset.upper())
    if not url:
        return []
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[FETCH] {asset}: {e}")
    return []


# Max gap between a signal's stored entry and the live price for the signal
# to still count as "fresh". Old signals have prices far from the market.
FRESH_ENTRY_BAND = 0.02   # 2 %


def signal_tradeable(sig: dict, symbol: str) -> tuple:
    """Return (ok, reason).

    Only trade a signal that is still FRESH — its stored entry is near the
    current price — AND whose SL/TP sit on the correct sides of the live
    price. Stale signals (old prices) are skipped here instead of being
    sent to MT5, which would reject them ('invalid stops') and spam alerts.
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, "no live price"
    px = (tick.ask + tick.bid) / 2.0

    tp = sig.get("trade_params", {}) or {}
    entry = float(tp.get("entry", sig.get("entry",  0)) or 0)
    sl    = float(tp.get("sl",    sig.get("sl",     0)) or 0)
    t2    = float(tp.get("t2",    sig.get("target", 0)) or 0)
    direction = sig.get("direction", "LONG")

    if not (entry and sl and t2):
        return False, "missing price levels"
    if abs(px - entry) / px > FRESH_ENTRY_BAND:
        return False, f"stale (entry {entry} vs market {px:.2f})"
    if direction == "LONG"  and not (sl < px < t2):
        return False, "SL/TP invalid for LONG at current price"
    if direction == "SHORT" and not (t2 < px < sl):
        return False, "SL/TP invalid for SHORT at current price"
    return True, "fresh"


# ═══════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  MT5 Auto-Trader — Gold + Bitcoin")
    print("  Press Ctrl+C to stop")
    print("=" * 60)

    if not connect():
        print("[MT5] Could not connect. Is MT5 terminal open and logged in?")
        sys.exit(1)

    traded_ids: set = set()    # signal IDs already traded this session
    assets = CFG.get("assets", ["GOLD", "BTC"])
    max_pos = CFG.get("max_positions_per_asset", 1)

    print(f"\n[BOT] Watching assets: {assets}")
    print(f"[BOT] Risk per trade: {CFG.get('risk_pct', 1.0)}%")
    print(f"[BOT] Max positions per asset: {max_pos}")
    print(f"[BOT] Polling every {POLL_SEC}s\n")

    while True:
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        print(f"[{now.strftime('%H:%M:%S IST')}] Polling signals...")

        for asset in assets:
            symbol = SYMBOL_MAP.get(asset, asset)

            # Check if MT5 is still connected
            if not mt5.terminal_info():
                print("[MT5] Lost connection — reconnecting...")
                if not connect():
                    time.sleep(30)
                    continue

            # Check open position count
            open_pos = count_open_positions(symbol)
            if open_pos >= max_pos:
                print(f"[{asset}] {open_pos} position(s) already open — skipping new entries")
                continue

            # Fetch latest signals from GitHub
            signals = fetch_signals(asset)
            if not signals:
                print(f"[{asset}] No signals found")
                continue

            # Find signals with OPEN status not yet traded
            new_signals = [
                s for s in signals
                if s.get("status") == "OPEN"
                and s.get("id") not in traded_ids
            ]

            if not new_signals:
                print(f"[{asset}] No new signals")
                continue

            # Take the highest-scored signal that is still FRESH + valid.
            # Stale signals are skipped and marked seen so we neither recheck
            # them every cycle nor send rejected orders to MT5.
            new_signals.sort(key=lambda x: x.get("score", 0), reverse=True)

            sig = None
            for cand in new_signals:
                ok, why = signal_tradeable(cand, symbol)
                if ok:
                    sig = cand
                    break
                traded_ids.add(cand.get("id"))   # skip stale/invalid, don't retry
                print(f"[{asset}] skip #{cand.get('id')}: {why}")

            if sig is None:
                print(f"[{asset}] No fresh tradeable signal")
                continue

            sig_id = sig.get("id")
            score  = sig.get("score", 0)
            print(f"[{asset}] NEW signal #{sig_id}  score={score}/150  "
                  f"{sig.get('direction')}  entry={sig.get('trade_params',{}).get('entry','?')}")

            # Place the order
            success = place_order(sig)
            traded_ids.add(sig_id)   # mark as processed (win or fail)

            if success:
                print(f"[{asset}] Trade placed for signal #{sig_id}")
            else:
                print(f"[{asset}] Trade failed for signal #{sig_id}")

        # Report any closed trades
        report_closed_trades()

        time.sleep(POLL_SEC)


# ═══════════════════════════════════════════════════════════════════
# CONFIG FILE GENERATOR
# ═══════════════════════════════════════════════════════════════════

def generate_config():
    """Run this once to create your mt5_config.json."""
    sample = {
        "_instructions": "Fill in your MT5 demo account details below",
        "login":    12345678,
        "password": "YourDemoPassword",
        "server":   "XMGlobal-Demo",
        "path":     "",
        "risk_pct": 1.0,
        "telegram_token":   "your_bot_token_here",
        "telegram_chat_id": "your_chat_id_here",
        "github_user": "lavakus",
        "github_repo": "nse-intraday-bot",
        "assets":   ["GOLD", "BTC"],
        "max_positions_per_asset": 1,
        "symbol_gold": "XAUUSD",
        "symbol_btc":  "BTCUSD",
        "_broker_notes": {
            "XM":         "symbol_gold=XAUUSD, symbol_btc=BTCUSD, server=XMGlobal-Demo",
            "ICMarkets":  "symbol_gold=XAUUSD, symbol_btc=BTCUSD, server=ICMarketsSC-Demo",
            "Exness":     "symbol_gold=XAUUSDm, symbol_btc=BTCUSDm, server=Exness-Trial",
            "Pepperstone":"symbol_gold=XAUUSD, symbol_btc=BTCUSD, server=Pepperstone-Demo",
        }
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=2)
    print(f"✅ Created {CONFIG_FILE} — fill in your details and run: python mt5_trader.py")


if __name__ == "__main__":
    if "--setup" in sys.argv:
        generate_config()
    else:
        main()
