"""
Notifier — Desktop + Telegram fire TOGETHER.
Rule: Desktop only shows if Telegram send succeeds (ok=True).
Both carry identical content so user sees the same alert on both.
"""
import threading
import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ── SHARED MESSAGE BUILDER ─────────────────────────────────────
def _message(sig: dict) -> str:
    action = "BUY" if sig["direction"] == "LONG" else "SELL"
    bar    = "#" * int(sig["score"]) + "." * (10 - int(sig["score"]))
    lines  = [
        f"*** NSE INTRADAY ALERT ***",
        f"",
        f"Stock  : {sig['symbol']}",
        f"Action : {action}",
        f"Score  : {sig['score']}/10  [{bar}]",
        f"",
        f"Entry  : Rs {sig['entry']}",
        f"Target : Rs {sig['target']}",
        f"SL     : Rs {sig['sl']}",
        f"R:R    : 1 : {sig['rr']}",
        f"",
        f"RSI    : {sig['rsi']}",
        f"VWAP   : Rs {sig['vwap']}",
        f"Volume : {sig['vol_ratio']}x average",
        f"",
        f"Signals confirmed:",
    ] + [f"  + {r}" for r in sig.get("reasons", [])] + [
        f"",
        f"Use SL strictly. Trade at your own risk.",
    ]
    return "\n".join(lines)


# ── TELEGRAM ───────────────────────────────────────────────────
def _send_telegram(sig: dict) -> bool:
    try:
        r    = requests.post(
            f"{BASE}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": _message(sig)},
            timeout=10,
        )
        ok = r.json().get("ok", False)
        print(f"  [TELEGRAM] {sig['symbol']} -> {'SENT' if ok else 'FAILED: ' + r.json().get('description','')}")
        return ok
    except Exception as e:
        print(f"  [TELEGRAM ERROR] {e}")
        return False


# ── DESKTOP ────────────────────────────────────────────────────
def _send_desktop(sig: dict):
    try:
        from winotify import Notification, audio
        action = "BUY" if sig["direction"] == "LONG" else "SELL"
        n = Notification(
            app_id   = "NSE Intraday Bot",
            title    = f"NSE {action}: {sig['symbol']}  |  Score {sig['score']}/10",
            msg      = (
                f"Entry : Rs {sig['entry']}\n"
                f"Target: Rs {sig['target']}\n"
                f"SL    : Rs {sig['sl']}"
            ),
            duration = "long",
        )
        n.set_audio(audio.Default, loop=False)
        n.show()
        print(f"  [DESKTOP]  {sig['symbol']} -> SHOWN")
    except Exception as e:
        print(f"  [DESKTOP ERROR] {e}")


# ── PLAIN TELEGRAM UTILITY (used by bot for non-alert messages) ─
def telegram_send(text: str, chat_id: str = TELEGRAM_CHAT_ID, markup: dict = None):
    payload = {"chat_id": chat_id, "text": text}
    if markup:
        payload["reply_markup"] = markup
    try:
        r = requests.post(f"{BASE}/sendMessage", json=payload, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"[TELEGRAM SEND ERROR] {e}")
        return False


# ── FIRE ALERT — BOTH TOGETHER ─────────────────────────────────
def fire_alert(sig: dict):
    """Send alert to Telegram and log to dashboard."""
    sym = sig["symbol"]
    print(f"\n[ALERT] {sym}  {sig['direction']}  score={sig['score']}  "
          f"entry={sig['entry']}  target={sig['target']}  SL={sig['sl']}")

    # ── LOG TO DASHBOARD ──────────────────────────────────────
    try:
        from signal_logger import log_signal
        log_signal(sig)
    except Exception as e:
        print(f"  [LOG ERROR] {e}")

    # ── SEND TO TELEGRAM ──────────────────────────────────────
    ok = _send_telegram(sig)
    if not ok:
        print(f"  [RETRY] {sym}...")
        ok = _send_telegram(sig)

    print(f"  [ALERT COMPLETE] {sym} — Telegram {'SENT' if ok else 'FAILED'}")
