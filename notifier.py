"""
Notifier — Telegram alerts for SMC + ICT signals.
Credentials always read from environment variables first,
falling back to config.py for local development.
"""
import os
import requests

# Env vars take priority (GitHub Actions secrets), then config.py for local dev
_TOKEN   = os.environ.get("TELEGRAM_TOKEN")   or ""
_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or ""

# Fallback: config.py (local dev only — never rely on this in production)
if not _TOKEN or not _CHAT_ID:
    try:
        from config import TELEGRAM_TOKEN as _CFG_TOKEN, TELEGRAM_CHAT_ID as _CFG_CHAT
        _TOKEN   = _TOKEN   or _CFG_TOKEN
        _CHAT_ID = _CHAT_ID or _CFG_CHAT
    except Exception:
        pass

if not _TOKEN:
    print("[NOTIFIER] WARNING: TELEGRAM_TOKEN not set — alerts will fail")

TELEGRAM_TOKEN   = _TOKEN
TELEGRAM_CHAT_ID = _CHAT_ID
BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ── MESSAGE BUILDER ────────────────────────────────────────────

def _message(sig: dict) -> str:
    action   = sig.get("signal", "BUY" if sig.get("direction") == "LONG" else "SELL")
    score    = sig.get("score", 0)
    pct      = sig.get("score_pct", round(score / 150 * 100, 1))
    strength = sig.get("signal_strength", "GOOD")
    kz       = sig.get("kill_zone", "?")
    ph       = sig.get("phase_scores", {})
    tp       = sig.get("trade_params", {})
    entry    = tp.get("entry", sig.get("entry", "?"))
    sl       = tp.get("sl",    sig.get("sl",    "?"))
    t1       = tp.get("t1",    sig.get("t1",    "?"))
    t2       = tp.get("t2",    sig.get("t2",    "?"))
    rr       = tp.get("rr_ratio", sig.get("rr", "?"))
    sl_pct   = tp.get("sl_pct", "?")
    chk      = sig.get("must_have_checklist", {})

    bar = "#" * int(score // 15) + "." * (10 - int(score // 15))

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
        f"--- MUST-HAVE CHECKLIST ---",
        f"{'OK' if chk.get('bos_or_choch_15min') else 'XX'}  BOS/CHOCH on 15min",
        f"{'OK' if chk.get('order_block_valid')   else 'XX'}  Unmitigated Order Block",
        f"{'OK' if chk.get('liquidity_sweep')     else 'XX'}  Liquidity Sweep",
        f"{'OK' if chk.get('inside_kill_zone')    else 'XX'}  Inside Kill Zone",
        f"",
        f"--- CONFIRMED SIGNALS ---",
    ] + [f"  + {r}" for r in sig.get("reasons", [])] + [
        f"",
        f"RSI  : {sig.get('rsi', '?')}    VWAP : Rs {sig.get('vwap', '?')}",
        f"Vol  : {sig.get('vol_ratio', '?')}x average",
        f"",
        f"Move SL to breakeven when T1 is hit.",
        f"Max risk 0.5% of capital per trade.",
        f"Trade at your own risk.",
    ]
    return "\n".join(lines)


# ── TELEGRAM SEND ──────────────────────────────────────────────

def _send_telegram(sig: dict) -> bool:
    try:
        r  = requests.post(
            f"{BASE}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": _message(sig)},
            timeout=10,
        )
        ok = r.json().get("ok", False)
        print(f"  [TELEGRAM] {sig['symbol']} -> "
              f"{'SENT' if ok else 'FAILED: ' + r.json().get('description', '')}")
        return ok
    except Exception as e:
        print(f"  [TELEGRAM ERROR] {e}")
        return False


# ── PLAIN UTILITY (bot commands, greetings, etc.) ──────────────

def telegram_send(text: str, chat_id: str = None,
                  markup: dict = None) -> bool:
    chat_id = chat_id or TELEGRAM_CHAT_ID
    payload = {"chat_id": chat_id, "text": text}
    if markup:
        payload["reply_markup"] = markup
    try:
        r = requests.post(f"{BASE}/sendMessage", json=payload, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"[TELEGRAM SEND ERROR] {e}")
        return False


# ── FIRE ALERT ─────────────────────────────────────────────────

def fire_alert(sig: dict):
    """Log signal to dashboard + send to Telegram."""
    sym = sig["symbol"]
    print(f"\n[ALERT] {sym}  {sig.get('signal','?')}  "
          f"score={sig.get('score','?')}/150  "
          f"entry={sig.get('entry','?')}  "
          f"t1={sig.get('t1','?')}  t2={sig.get('t2','?')}  "
          f"sl={sig.get('sl','?')}")

    # ── Log to dashboard ──────────────────────────────────────
    try:
        from signal_logger import log_signal
        log_signal(sig)
    except Exception as e:
        print(f"  [LOG ERROR] {e}")

    # ── Send to Telegram (with one retry) ─────────────────────
    ok = _send_telegram(sig)
    if not ok:
        print(f"  [RETRY] {sym}...")
        ok = _send_telegram(sig)

    print(f"  [ALERT COMPLETE] {sym} — Telegram {'SENT' if ok else 'FAILED'}")
