"""
Gold (XAUUSD) scanner — runs standalone or inside run_all.py.
Sends Telegram alert when score >= MIN_SCORE (65/150).
Can be run by GitHub Actions cron for 24/5 coverage.
"""
import os, time, json
from datetime import datetime, timezone, timedelta

from gold_strategy  import score_gold
from feeds.gold_feed import get_gold_data, get_prev_day_high_low, get_asian_session_range
from feeds.dxy_feed  import get_dxy_data
from signal_logger   import log_signal
from notifier        import telegram_send
from shared.smc_engine import get_kill_zone

THRESHOLD = float(os.environ.get("GOLD_SCORE", "65"))
BOT_STATE_FILE = "bot_state.json"
GOLD_LOG_FILE  = "gold_signals_log.json"


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _is_paused() -> bool:
    try:
        with open(BOT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("GOLD", {}).get("paused", False)
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"[GOLD] bot_state read error: {e}")
        return False


def _format_gold_alert(sig: dict) -> str:
    tp = sig.get("trade_params", {})
    ph = sig.get("phase_scores", {})
    chk = sig.get("must_have_checklist", {})
    bar = "#" * int(sig["score"] // 15) + "." * (10 - int(sig["score"] // 15))

    lines = [
        f"*** GOLD SIGNAL — {sig['signal']} ***",
        f"",
        f"Asset     : Gold (XAUUSD)",
        f"Score     : {sig['score']}/150  ({sig['score_pct']}%)  [{bar}]",
        f"Strength  : {sig['signal_strength']}",
        f"Kill Zone : {sig['kill_zone']}",
        f"DXY       : {'Confirms' if sig.get('dxy_confirmation') else 'Not confirmed'}",
        f"",
        f"Entry  : ${tp.get('entry', '?')}",
        f"SL     : ${tp.get('sl', '?')}  ({tp.get('sl_pct', '?')}%)",
        f"T1     : ${tp.get('t1', '?')}  (RR 1:{tp.get('rr_t1', '?')})",
        f"T2     : ${tp.get('t2', '?')}  (RR 1:{tp.get('rr_t2', '?')})",
        f"",
        f"SMC Structure  : {ph.get('smc_structure','?')}/60",
        f"ICT Gold       : {ph.get('ict_gold_filters','?')}/40",
        f"PA + Boosters  : {ph.get('pa_boosters','?')}/50",
        f"",
        f"{'OK' if chk.get('bos_or_choch_1h') else 'XX'}  BOS/CHOCH 1H",
        f"{'OK' if chk.get('order_block_valid') else 'XX'}  Order Block",
        f"{'OK' if chk.get('liquidity_sweep') else 'XX'}  Liquidity Sweep",
        f"{'OK' if chk.get('inside_kill_zone') else 'XX'}  Kill Zone",
        f"",
    ] + [f"  + {r}" for r in sig.get("reasons", [])] + [
        f"",
        f"Move SL to breakeven at T1. Max 0.5% capital risk.",
        f"Trade Gold at your own risk.",
    ]
    return "\n".join(lines)


def scan_gold_once() -> dict | None:
    """Run one Gold scan. Returns signal dict or None."""
    ist = _now_ist()
    print(f"[GOLD] Scanning — {ist.strftime('%H:%M IST')}")

    try:
        data = get_gold_data()
        if data["price"] is None:
            print("[GOLD] No price data")
            return None

        pdh, pdl = get_prev_day_high_low()
        dxy      = get_dxy_data()

        sig = score_gold(
            df_4h  = data["df_4h"],
            df_1h  = data["df_1h"],
            df_15m = data["df_15m"],
            pdh=pdh, pdl=pdl,
            dxy_data=dxy,
            ist_time=ist,
        )

        kz, kz_pts = get_kill_zone("GOLD", ist.hour, ist.minute)
        print(f"[GOLD] Kill Zone: {kz} (pts={kz_pts}) | Price={data['price']}")

        if sig and sig.get("score", 0) >= THRESHOLD:
            print(f"[GOLD] STRONG: {sig['signal']} "
                  f"score={sig['score']}/150 [{sig['signal_strength']}] "
                  f"entry={sig['entry']} T1={sig['t1']} T2={sig['t2']}")
            return sig
        elif sig and isinstance(sig, dict) and sig.get("score", 0) > 0:
            print(f"[GOLD] Signal found but score {sig.get('score',0)}/150 < threshold {THRESHOLD}")
        else:
            if kz_pts == 0:
                print(f"[GOLD] Blocked — not in a kill zone (current: {kz})")
            else:
                print("[GOLD] Blocked — BOS/CHOCH, Order Block, or Liquidity Sweep not confirmed")
    except Exception as e:
        print(f"[GOLD] Scan error: {e}")
    return None


def run_gold_watcher():
    """Continuous 15-minute scan loop for Gold (for local run_all.py)."""
    print("[GOLD] Watcher started — scanning every 15 min")
    alerted_today = set()
    last_date     = None

    while True:
        ist   = _now_ist()
        today = ist.date()

        if last_date != today:
            alerted_today = set()
            last_date     = today

        if _is_paused():
            print("[GOLD] Paused — sleeping 60s")
            time.sleep(60)
            continue

        sig = scan_gold_once()
        if sig:
            key = f"{sig['signal']}_{sig['entry']}"
            if key not in alerted_today:
                alerted_today.add(key)
                log_signal(sig)
                telegram_send(_format_gold_alert(sig))
                print("[GOLD] Alert fired and logged")

        time.sleep(15 * 60)   # scan every 15 minutes


# ── Standalone entry (for GitHub Actions or direct run) ─────────

def main():
    ist = _now_ist()
    print(f"[GOLD] One-shot scan — {ist.strftime('%A %H:%M IST')}")

    sig = scan_gold_once()
    if sig:
        log_signal(sig)
        ok = telegram_send(_format_gold_alert(sig))
        print(f"[GOLD] Telegram: {'SENT' if ok else 'FAILED'}")
    else:
        print("[GOLD] No strong setup — no alert sent")


if __name__ == "__main__":
    main()
