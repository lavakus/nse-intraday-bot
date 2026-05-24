"""
Bitcoin (BTCUSDT) scanner — runs standalone or inside run_all.py.
Sends Telegram alert when score >= MIN_SCORE (65/150).
Can be run by GitHub Actions cron for 24/7 coverage.
"""
import os, time, json
from datetime import datetime, timezone, timedelta

from btc_strategy       import score_btc
from feeds.btc_feed     import get_btc_data, get_prev_day_high_low, get_cme_gap
from feeds.funding_rate import get_funding_rate
from feeds.fear_greed   import get_fear_greed
from signal_logger       import log_signal
from notifier            import telegram_send

THRESHOLD      = float(os.environ.get("BTC_SCORE", "65"))
BOT_STATE_FILE = "bot_state.json"


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _is_paused() -> bool:
    try:
        with open(BOT_STATE_FILE) as f:
            return json.load(f).get("BTC", {}).get("paused", False)
    except Exception:
        return False


def _format_btc_alert(sig: dict) -> str:
    tp  = sig.get("trade_params", {})
    ph  = sig.get("phase_scores", {})
    chk = sig.get("must_have_checklist", {})
    cme = sig.get("cme_gap", {})
    bar = "#" * int(sig["score"] // 15) + "." * (10 - int(sig["score"] // 15))

    lines = [
        f"*** BITCOIN SIGNAL — {sig['signal']} ***",
        f"",
        f"Asset     : Bitcoin (BTCUSDT)",
        f"Score     : {sig['score']}/150  ({sig['score_pct']}%)  [{bar}]",
        f"Strength  : {sig['signal_strength']}",
        f"Kill Zone : {sig['kill_zone']}",
        f"Funding   : {sig.get('funding_rate', '?')}%",
        f"Fear/Greed: {sig.get('fear_greed_index', '?')}",
        f"",
        f"Entry  : ${tp.get('entry', '?'):,}",
        f"SL     : ${tp.get('sl', '?'):,}  ({tp.get('sl_pct', '?')}%)",
        f"T1     : ${tp.get('t1', '?'):,}  (RR 1:{tp.get('rr_t1', '?')})",
        f"T2     : ${tp.get('t2', '?'):,}  (RR 1:{tp.get('rr_t2', '?')})",
        f"",
        f"CME Gap Below : ${cme.get('nearest_gap_below') or 'None':,}"
            if cme.get('nearest_gap_below') else f"CME Gap Below : None",
        f"CME Gap Above : ${cme.get('nearest_gap_above') or 'None':,}"
            if cme.get('nearest_gap_above') else f"CME Gap Above : None",
        f"",
        f"SMC Structure    : {ph.get('smc_structure','?')}/60",
        f"ICT Crypto       : {ph.get('ict_crypto_filters','?')}/52",
        f"PA + Boosters    : {ph.get('pa_boosters','?')}/38",
        f"",
        f"{'OK' if chk.get('bos_or_choch_4h') else 'XX'}  BOS/CHOCH 4H",
        f"{'OK' if chk.get('order_block_valid') else 'XX'}  Order Block",
        f"{'OK' if chk.get('liquidity_sweep') else 'XX'}  Liquidity Sweep",
        f"{'OK' if chk.get('inside_kill_zone') else 'XX'}  Kill Zone",
        f"",
    ] + [f"  + {r}" for r in sig.get("reasons", [])] + [
        f"",
        f"Check funding rate before entry. Move SL to breakeven at T1.",
        f"Trade BTC at your own risk.",
    ]
    return "\n".join(lines)


def scan_btc_once() -> dict | None:
    """Run one BTC scan. Returns signal dict or None."""
    ist = _now_ist()
    print(f"[BTC] Scanning — {ist.strftime('%H:%M IST')}")

    try:
        data     = get_btc_data()
        pdh, pdl = get_prev_day_high_low()
        funding  = get_funding_rate("BTCUSDT")
        fg       = get_fear_greed()
        cme      = get_cme_gap()

        print(f"[BTC] Price=${data['price']:,.0f}  "
              f"Funding={funding['rate_pct']}%  "
              f"F&G={fg['value']} ({fg['label']})")

        sig = score_btc(
            df_weekly  = data["df_weekly"],
            df_4h      = data["df_4h"],
            df_1h      = data["df_1h"],
            df_15m     = data["df_15m"],
            pdh=pdh, pdl=pdl,
            funding    = funding,
            fear_greed = fg,
            cme_gap    = cme,
            ist_time   = ist,
        )

        if sig and sig.get("score", 0) >= THRESHOLD:
            print(f"[BTC] STRONG: {sig['signal']} "
                  f"score={sig['score']}/150 [{sig['signal_strength']}] "
                  f"entry=${sig['entry']:,} T2=${sig['t2']:,}")
            return sig
        else:
            print("[BTC] No qualifying signal this scan")
    except Exception as e:
        print(f"[BTC] Scan error: {e}")
    return None


def run_btc_watcher():
    """Continuous 15-minute scan loop for BTC (for local run_all.py)."""
    print("[BTC] Watcher started — scanning every 15 min")
    alerted_today = set()
    last_date     = None

    while True:
        ist   = _now_ist()
        today = ist.date()

        if last_date != today:
            alerted_today = set()
            last_date     = today

        if _is_paused():
            print("[BTC] Paused — sleeping 60s")
            time.sleep(60)
            continue

        sig = scan_btc_once()
        if sig:
            key = f"{sig['signal']}_{sig['entry']}"
            if key not in alerted_today:
                alerted_today.add(key)
                log_signal(sig)
                telegram_send(_format_btc_alert(sig))
                print("[BTC] Alert fired and logged")

        time.sleep(15 * 60)


# ── Standalone entry ─────────────────────────────────────────────

def main():
    ist = _now_ist()
    print(f"[BTC] One-shot scan — {ist.strftime('%A %H:%M IST')}")

    sig = scan_btc_once()
    if sig:
        log_signal(sig)
        ok = telegram_send(_format_btc_alert(sig))
        print(f"[BTC] Telegram: {'SENT' if ok else 'FAILED'}")
    else:
        print("[BTC] No strong setup — no alert sent")


if __name__ == "__main__":
    main()
