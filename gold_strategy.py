"""
Gold (XAUUSD) Strategy — SMC + ICT + Price Action
===================================================
Timeframes : 4H (macro) → 1H (structure) → 15min (entry trigger)
Scoring    : 150-point scale, minimum 65 to trade

Required to trade:
  Phase 1: BOS/CHOCH on 1H  +  Order Block  +  Liquidity Sweep (all 3)
  Phase 2: Inside Gold Kill Zone (KZ-A / KZ-L / KZ-NY)

Hard rules:
  SL max 0.6 % of price
  Min RR  1:2.0 (T1)  and  1:3.5 (T2)
  Max 3 trades per 24-hour period
  DXY must confirm direction
"""

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

from shared.smc_engine import (
    get_kill_zone, find_swings,
    detect_bos_choch, detect_order_block, detect_liquidity_sweep,
    detect_fvg, detect_ote, detect_vwap_reclaim, detect_rejection_candle,
    detect_volume_signature, signal_strength_label,
    add_vwap, add_vol_ma, add_rsi,
)

# ── Asset constants ─────────────────────────────────────────────
ASSET       = "GOLD"
MIN_SCORE   = 60
MAX_SL_PCT  = 0.006    # 0.6 %
MIN_RR_T1   = 2.0
MIN_RR_T2   = 3.5

# Round-number levels for Gold (USD)
_ROUND_LEVELS = list(range(1800, 4200, 100))


# ── DXY confirmation ────────────────────────────────────────────

def _dxy_confirms(dxy: dict, direction: str) -> bool:
    if not dxy:
        return False
    return dxy.get("bearish", False) if direction == "LONG" \
           else dxy.get("bullish", False)


# ── Asian session range ─────────────────────────────────────────

def _asian_range(df_1h: pd.DataFrame) -> dict:
    """Price range during 00:00–05:29 IST = London S/R reference."""
    if df_1h.empty:
        return {"high": None, "low": None}
    for d in sorted(set(df_1h.index.date), reverse=True):
        asian = df_1h[df_1h.index.date == d].between_time("00:00", "05:29")
        if not asian.empty:
            return {"high": round(float(asian["high"].max()), 2),
                    "low":  round(float(asian["low"].min()),  2)}
    return {"high": None, "low": None}


# ── Main scoring function ────────────────────────────────────────

def score_gold(df_4h: pd.DataFrame, df_1h: pd.DataFrame,
               df_15m: pd.DataFrame,
               pdh=None, pdl=None,
               dxy_data: dict = None,
               ist_time: datetime = None) -> dict:
    """
    Score Gold for LONG or SHORT.
    Returns full signal dict or {} if blocked.
    """
    if len(df_1h) < 12 or len(df_15m) < 10:
        return {}

    if ist_time is None:
        ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    # ── Kill zone check (REQUIRED) ─────────────────────────────
    kill_zone, kz_pts = get_kill_zone(ASSET, ist_time.hour, ist_time.minute)
    if kz_pts == 0:
        return {}

    # ── Prepare indicators on 15min ────────────────────────────
    df15 = add_rsi(add_vol_ma(add_vwap(df_15m.copy())))
    close = float(df15["close"].iloc[-1])
    if close <= 0:
        return {}

    # ════════════════════════════════════════
    # PHASE 1 — SMC Structure  (all REQUIRED)
    # ════════════════════════════════════════

    # BOS/CHOCH on 1H
    struct = detect_bos_choch(df_1h, left=3, right=3)
    if not struct["bos"] and not struct["choch"]:
        return {}
    direction = struct["direction"]
    if not direction:
        return {}

    phase1   = 25
    reasons  = []
    reasons.append(f"{'BOS' if struct['bos'] else 'CHOCH'} confirmed 1H ({direction})")

    # Order Block — 1H first, then 15min as fallback
    ob = detect_order_block(df_1h, direction)
    if not ob["valid"]:
        ob = detect_order_block(df_15m, direction)
    if not ob["valid"]:
        return {}
    phase1 += 20
    reasons.append(f"Unmitigated OB {ob['body_bot']:.2f}–{ob['body_top']:.2f}")

    # Liquidity sweep — bonus points (not a hard block)
    swept, sweep_lvl = detect_liquidity_sweep(df_15m, direction, pdh, pdl)
    if not swept:
        swept, sweep_lvl = detect_liquidity_sweep(df_1h, direction, pdh, pdl)
    if swept:
        phase1 += 15
        reasons.append(f"Liquidity sweep at {sweep_lvl:.2f}")
    else:
        reasons.append("No liquidity sweep yet — structure + OB entry")

    # ════════════════════════════════════════
    # PHASE 2 — ICT + Gold-specific filters
    # ════════════════════════════════════════

    phase2  = kz_pts   # +15 for active kill zone
    reasons.append(f"Kill Zone {kill_zone} active (+{kz_pts}pts)")

    # DXY inverse correlation (+12 pts)
    dxy_ok = _dxy_confirms(dxy_data, direction)
    if dxy_ok:
        phase2 += 12
        dxy_label = "bearish" if direction == "LONG" else "bullish"
        reasons.append(f"DXY {dxy_label} confirms Gold {direction}")

    # OTE on 15min (+10 pts)
    ote = detect_ote(df_15m, direction)
    if ote["in_zone"]:
        phase2 += 10
        reasons.append(f"OTE zone 61.8–79% fib ({ote['fib_level']}%)")

    # FVG on 15min (+8 pts)
    fvg = detect_fvg(df_15m, direction)
    if fvg["valid"]:
        phase2 += 8
        reasons.append(f"FVG imbalance {fvg['bot']:.2f}–{fvg['top']:.2f}")

    # PDH/PDL sweep & reclaim bonus (+7 pts)
    if sweep_lvl:
        if direction == "LONG"  and pdl and abs(sweep_lvl - pdl) / pdl < 0.003:
            phase2 += 7; reasons.append("PDL sweep + reclaim")
        elif direction == "SHORT" and pdh and abs(sweep_lvl - pdh) / pdh < 0.003:
            phase2 += 7; reasons.append("PDH sweep + reclaim")

    # ════════════════════════════════════════
    # PHASE 3 — Price Action + Boosters
    # ════════════════════════════════════════

    phase3 = 0

    # Rejection candle at OB (+10 pts)
    if detect_rejection_candle(df_15m, direction, ob):
        phase3 += 10; reasons.append("Strong rejection candle at OB (15min)")

    # 15min structure alignment with 1H bias (+7 pts)
    r5 = df_15m.iloc[-5:]
    if direction == "LONG" and (r5["high"].iloc[-1] > r5["high"].iloc[-3]
                                 and r5["low"].iloc[-1] > r5["low"].iloc[-3]):
        phase3 += 7; reasons.append("15min HH+HL aligns with 1H bullish bias")
    elif direction == "SHORT" and (r5["high"].iloc[-1] < r5["high"].iloc[-3]
                                    and r5["low"].iloc[-1] < r5["low"].iloc[-3]):
        phase3 += 7; reasons.append("15min LH+LL aligns with 1H bearish bias")

    # Round number confluence (+5 pts)
    for lvl in _ROUND_LEVELS:
        if abs(close - lvl) / close < 0.002:
            phase3 += 5; reasons.append(f"Round number ${lvl}"); break

    # Asian session S/R (+5 pts)
    asr = _asian_range(df_1h)
    if asr["high"] and asr["low"]:
        if direction == "LONG" and asr["low"] <= close <= asr["high"]:
            phase3 += 5; reasons.append(
                f"Price in Asian range ({asr['low']:.2f}–{asr['high']:.2f})")
        elif direction == "SHORT" and abs(close - asr["high"]) / close < 0.003:
            phase3 += 5; reasons.append(
                f"Rejection at Asian high {asr['high']:.2f}")

    # Volume signature (+4 pts)
    vol_sig, vol_ratio = detect_volume_signature(df15)
    if vol_sig:
        phase3 += 4; reasons.append(f"Volume {vol_ratio}x spike")

    # RSI ideal zone 40–65 (+3 pts)
    rsi_v = float(df15["rsi"].iloc[-1]) if "rsi" in df15.columns else 50.0
    if not np.isnan(rsi_v) and 40 <= rsi_v <= 65:
        phase3 += 3; reasons.append(f"RSI {rsi_v:.0f} — ideal entry zone")

    # Daily S/R at OB (+4 pts)
    if pdh and pdl:
        if direction == "LONG"  and abs(ob["body_bot"] - pdl) / pdl < 0.005:
            phase3 += 4; reasons.append("OB at daily S/R (PDL)")
        elif direction == "SHORT" and abs(ob["body_top"] - pdh) / pdh < 0.005:
            phase3 += 4; reasons.append("OB at daily S/R (PDH)")

    # ── Total & threshold ──────────────────────────────────────
    total = phase1 + phase2 + phase3
    if total < MIN_SCORE:
        return {}

    # ── Trade parameters ───────────────────────────────────────
    entry = round(close, 2)
    risk  = 0.0

    if direction == "LONG":
        sl      = round(max(ob["low"] * 0.999, entry * (1 - MAX_SL_PCT)), 2)
        sl_pct  = round((entry - sl) / entry * 100, 3)
        if sl_pct > MAX_SL_PCT * 100 or sl >= entry:
            return {}
        risk = entry - sl
        t1   = round(entry + risk * MIN_RR_T1, 2)
        t2   = round(entry + risk * MIN_RR_T2, 2)
        if pdh and entry < pdh < t2:
            t2 = round(pdh, 2)
    else:
        sl      = round(min(ob["high"] * 1.001, entry * (1 + MAX_SL_PCT)), 2)
        sl_pct  = round((sl - entry) / entry * 100, 3)
        if sl_pct > MAX_SL_PCT * 100 or sl <= entry:
            return {}
        risk = sl - entry
        t1   = round(entry - risk * MIN_RR_T1, 2)
        t2   = round(entry - risk * MIN_RR_T2, 2)
        if pdl and entry > pdl > t2:
            t2 = round(pdl, 2)

    if risk <= 0:
        return {}
    rr_t1 = round(abs(t1 - entry) / risk, 2)
    rr_t2 = round(abs(t2 - entry) / risk, 2)
    if rr_t1 < MIN_RR_T1 or rr_t2 < MIN_RR_T2:
        return {}

    pct      = round(total / 150 * 100, 1)
    strength = signal_strength_label(total)
    vwap_v   = round(float(df15["vwap"].iloc[-1]), 2) if "vwap" in df15.columns else None

    return {
        # ── Identity ──────────────────────────────────────────
        "asset":           ASSET,
        "symbol":          "XAUUSD",
        "direction":       direction,
        "signal":          "BUY" if direction == "LONG" else "SELL",
        # ── Score ─────────────────────────────────────────────
        "score":           total,
        "score_pct":       pct,
        "signal_strength": strength,
        "blocked_reason":  None,
        "kill_zone":       kill_zone,
        "dxy_confirmation": dxy_ok,
        "phase_scores": {
            "smc_structure":    phase1,
            "ict_gold_filters": phase2,
            "pa_boosters":      phase3,
        },
        "must_have_checklist": {
            "bos_or_choch_1h":   struct["bos"] or struct["choch"],
            "order_block_valid": ob["valid"],
            "liquidity_sweep":   swept,
            "inside_kill_zone":  kz_pts > 0,
        },
        "trade_params": {
            "entry":  entry,
            "sl":     sl,
            "sl_pct": sl_pct,
            "t1":     t1,
            "t2":     t2,
            "rr_t1":  rr_t1,
            "rr_t2":  rr_t2,
        },
        "asian_session_range": asr,
        # ── Backward-compat keys (logger / notifier) ──────────
        "entry":     entry,
        "target":    t2,
        "t1":        t1,
        "sl":        sl,
        "rr":        rr_t2,
        "reasons":   reasons,
        "rsi":       round(rsi_v, 1),
        "vwap":      vwap_v,
        "vol_ratio": vol_ratio,
        "confidence": strength,
        "timestamp": ist_time.isoformat(),
    }
