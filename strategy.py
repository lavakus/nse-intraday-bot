"""
SMC + ICT + Price Action Strategy  —  India Market
====================================================
Timeframes : 15min (structure/bias) + 5min (entry trigger)
Scoring    : 150-point scale.  Minimum 65 to trade.
             Phase 1 (60 pts, ALL required) + Phase 2 (40 pts, KZ required)
             + Phase 3 (27 pts) + Phase 4 (23 pts)

Hard blocks (return {} immediately):
  • Not in KZ1 / KZ2 / KZ3
  • No BOS or CHOCH on 15min
  • No valid unmitigated Order Block
  • No confirmed Liquidity Sweep
  • Score < 65  (sanity — practically unreachable if Phase 1 + KZ pass)
  • SL > 0.8 % of entry
  • R:R < 2.5
  • After 14:30 IST
  • Thursday expiry → only KZ3 allowed
"""

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta


# ══════════════════════════════════════════════════════════════════
# KILL ZONE CLASSIFIER
# ══════════════════════════════════════════════════════════════════

_KZ_TABLE = [
    (900,  914,  "PREP",  0),
    (915,  959,  "KZ1",  15),
    (1000, 1114, "DEAD",  0),
    (1115, 1144, "KZ2",  15),
    (1145, 1329, "DEAD",  0),
    (1330, 1414, "KZ3",  15),
    (1415, 1529, "LATE",  0),
    (1530, 1530, "CLOSE", 0),
]


def _get_kill_zone(hour: int, minute: int) -> tuple:
    """Returns (zone_name: str, score_pts: int)."""
    t = hour * 100 + minute
    for start, end, name, pts in _KZ_TABLE:
        if start <= t <= end:
            return name, pts
    return "OUTSIDE", 0


# ══════════════════════════════════════════════════════════════════
# SWING POINT DETECTION  (ZigZag-lite)
# ══════════════════════════════════════════════════════════════════

def _find_swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple:
    """
    Returns (swing_highs, swing_lows).
    Each is a list of (bar_index: int, price: float).
    """
    highs, lows = [], []
    n = len(df)
    for i in range(left, n - right):
        hi = df["high"].iloc[i]
        lo = df["low"].iloc[i]

        if hi == df["high"].iloc[i - left: i + right + 1].max():
            highs.append((i, float(hi)))

        if lo == df["low"].iloc[i - left: i + right + 1].min():
            lows.append((i, float(lo)))

    return highs, lows


# ══════════════════════════════════════════════════════════════════
# BOS / CHOCH  — 15 min
# ══════════════════════════════════════════════════════════════════

def _detect_bos_choch(df15: pd.DataFrame) -> dict:
    """
    BOS  = Break of Structure — continuation signal.
    CHOCH = Change of Character — reversal signal.
    Requires a candle CLOSE beyond the last confirmed swing.
    """
    empty = {"bos": False, "choch": False, "direction": None,
             "swing_high": None, "swing_low": None}

    if len(df15) < 10:
        return empty

    highs, lows = _find_swings(df15, left=2, right=2)
    if not highs or not lows:
        return empty

    sh_idx, sh_px = highs[-1]
    sl_idx, sl_px = lows[-1]
    last_close    = float(df15["close"].iloc[-1])

    result = dict(empty)
    result["swing_high"] = sh_px
    result["swing_low"]  = sl_px

    # Prior structure direction: whichever swing is more recent
    prior_bullish = sh_idx > sl_idx

    if prior_bullish:
        # BOS = close above last swing high (up-trend continuation)
        if last_close > sh_px:
            result["bos"]       = True
            result["direction"] = "LONG"
        # CHOCH = close below last swing low (reversal down)
        elif last_close < sl_px:
            result["choch"]     = True
            result["direction"] = "SHORT"
    else:
        # BOS = close below last swing low (down-trend continuation)
        if last_close < sl_px:
            result["bos"]       = True
            result["direction"] = "SHORT"
        # CHOCH = close above last swing high (reversal up)
        elif last_close > sh_px:
            result["choch"]     = True
            result["direction"] = "LONG"

    return result


# ══════════════════════════════════════════════════════════════════
# ORDER BLOCK DETECTION — 15 min
# ══════════════════════════════════════════════════════════════════

def _detect_order_block(df15: pd.DataFrame, direction: str) -> dict:
    """
    Bullish OB = last bearish candle before bullish BOS.
    Bearish OB = last bullish candle before bearish BOS.
    Valid only if unmitigated (price hasn't fully traded back through the body).
    """
    empty = {"valid": False, "high": None, "low": None,
             "body_top": None, "body_bot": None}

    n = len(df15)
    if n < 6:
        return empty

    # Scan backwards from bar -2 (skip the BOS/trigger candle itself)
    for i in range(n - 2, max(0, n - 30), -1):
        row = df15.iloc[i]
        o, c = float(row["open"]), float(row["close"])
        h, l = float(row["high"]),  float(row["low"])

        if direction == "LONG" and c < o:          # bearish candle = bullish OB
            body_top = o
            body_bot = c
            # Unmitigated: no subsequent close (excluding recent trigger bars) < body_bot
            future_lows = df15["low"].iloc[i + 1: n - 1]
            if len(future_lows) == 0 or future_lows.min() > body_bot:
                return {"valid": True, "high": h, "low": l,
                        "body_top": body_top, "body_bot": body_bot}

        elif direction == "SHORT" and c > o:       # bullish candle = bearish OB
            body_top = c
            body_bot = o
            future_highs = df15["high"].iloc[i + 1: n - 1]
            if len(future_highs) == 0 or future_highs.max() < body_top:
                return {"valid": True, "high": h, "low": l,
                        "body_top": body_top, "body_bot": body_bot}

    return empty


# ══════════════════════════════════════════════════════════════════
# LIQUIDITY SWEEP DETECTION — 5 min
# ══════════════════════════════════════════════════════════════════

def _detect_liquidity_sweep(df5: pd.DataFrame, direction: str,
                             pdh=None, pdl=None) -> tuple:
    """
    Buy  setup: price swept BELOW equal lows / PDL / swing low, then closed ABOVE.
    Sell setup: price swept ABOVE equal highs / PDH / swing high, then closed BELOW.
    Returns (swept: bool, sweep_level: float | None).
    """
    if len(df5) < 4:
        return False, None

    lookback = min(30, len(df5) - 1)
    recent   = df5.iloc[-lookback - 1: -1]   # exclude current candle
    prev     = df5.iloc[-2]
    last     = df5.iloc[-1]
    cur_close = float(last["close"])

    if direction == "LONG":
        # 1. Previous-day low sweep
        if pdl and float(prev["low"]) < pdl and cur_close > pdl:
            return True, round(float(pdl), 2)

        # 2. Equal lows (within 0.15 %)
        lows = recent["low"].values
        for i in range(len(lows) - 1, max(0, len(lows) - 20), -1):
            for j in range(i - 1, max(-1, i - 8), -1):
                tol = lows[j] * 0.0015
                if abs(lows[i] - lows[j]) <= tol:
                    level = min(lows[i], lows[j])
                    if float(prev["low"]) < level and cur_close > level:
                        return True, round(float(level), 2)

        # 3. Generic swing-low sweep
        swing_low = float(recent["low"].min())
        if float(prev["low"]) < swing_low and cur_close > swing_low:
            return True, round(swing_low, 2)

    else:  # SHORT
        # 1. Previous-day high sweep
        if pdh and float(prev["high"]) > pdh and cur_close < pdh:
            return True, round(float(pdh), 2)

        # 2. Equal highs (within 0.15 %)
        highs = recent["high"].values
        for i in range(len(highs) - 1, max(0, len(highs) - 20), -1):
            for j in range(i - 1, max(-1, i - 8), -1):
                tol = highs[j] * 0.0015
                if abs(highs[i] - highs[j]) <= tol:
                    level = max(highs[i], highs[j])
                    if float(prev["high"]) > level and cur_close < level:
                        return True, round(float(level), 2)

        # 3. Generic swing-high sweep
        swing_high = float(recent["high"].max())
        if float(prev["high"]) > swing_high and cur_close < swing_high:
            return True, round(swing_high, 2)

    return False, None


# ══════════════════════════════════════════════════════════════════
# FAIR VALUE GAP — 3-candle imbalance
# ══════════════════════════════════════════════════════════════════

def _detect_fvg(df: pd.DataFrame, direction: str, lookback: int = 20) -> dict:
    """
    Bullish FVG : candle[i].high  < candle[i+2].low   (gap between them)
    Bearish FVG : candle[i].low   > candle[i+2].high
    Valid only if not yet filled by subsequent price action.
    """
    empty = {"valid": False, "top": None, "bot": None}
    n = len(df)
    if n < 3:
        return empty

    for i in range(n - 3, max(0, n - lookback - 3), -1):
        c1_h = float(df["high"].iloc[i])
        c1_l = float(df["low"].iloc[i])
        c3_h = float(df["high"].iloc[i + 2])
        c3_l = float(df["low"].iloc[i + 2])

        if direction == "LONG":
            gap_bot, gap_top = c1_h, c3_l
            if gap_top > gap_bot:
                future_lows = df["low"].iloc[i + 2:]
                if float(future_lows.min()) > gap_bot:
                    return {"valid": True,
                            "top": round(gap_top, 2),
                            "bot": round(gap_bot, 2)}

        elif direction == "SHORT":
            gap_top, gap_bot = c1_l, c3_h
            if gap_top > gap_bot:
                future_highs = df["high"].iloc[i + 2:]
                if float(future_highs.max()) < gap_top:
                    return {"valid": True,
                            "top": round(gap_top, 2),
                            "bot": round(gap_bot, 2)}

    return empty


# ══════════════════════════════════════════════════════════════════
# OTE — FIBONACCI OPTIMAL TRADE ENTRY (61.8 – 79 %)
# ══════════════════════════════════════════════════════════════════

def _detect_ote(df5: pd.DataFrame, direction: str) -> bool:
    """True when current price is retracing into the 61.8–79 % fib zone."""
    if len(df5) < 10:
        return False

    highs, lows = _find_swings(df5, left=2, right=2)
    if not highs or not lows:
        return False

    close = float(df5["close"].iloc[-1])

    if direction == "LONG":
        sh_idx, sh_px = highs[-1]
        sl_idx, sl_px = lows[-1]
        if sh_idx <= sl_idx or sh_px <= sl_px:
            return False
        rng     = sh_px - sl_px
        fib_618 = sh_px - 0.618 * rng
        fib_790 = sh_px - 0.790 * rng
        return fib_790 <= close <= fib_618

    else:  # SHORT
        sh_idx, sh_px = highs[-1]
        sl_idx, sl_px = lows[-1]
        if sl_idx <= sh_idx or sh_px <= sl_px:
            return False
        rng     = sh_px - sl_px
        fib_618 = sl_px + 0.618 * rng
        fib_790 = sl_px + 0.790 * rng
        return fib_618 <= close <= fib_790


# ══════════════════════════════════════════════════════════════════
# INDICATOR HELPERS
# ══════════════════════════════════════════════════════════════════

def _vwap(df: pd.DataFrame) -> pd.DataFrame:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df = df.copy()
    df["vwap"] = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
    return df


def _vol_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(period, min_periods=5).mean()
    return df


def _rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    d    = df["close"].diff()
    gain = d.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs   = gain / loss.replace(0, np.nan)
    df   = df.copy()
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


# ══════════════════════════════════════════════════════════════════
# PHASE 3 HELPERS
# ══════════════════════════════════════════════════════════════════

def _detect_vwap_reclaim(df5: pd.DataFrame, direction: str) -> bool:
    """
    LONG : at least one recent candle closed BELOW vwap AND current close is ABOVE vwap.
    SHORT: at least one recent candle closed ABOVE vwap AND current close is BELOW vwap.
    Not just "price is above/below vwap" — requires an actual reclaim.
    """
    if len(df5) < 5 or "vwap" not in df5.columns:
        return False

    recent = df5.iloc[-8:]
    if direction == "LONG":
        dipped  = (recent["close"].iloc[:-1] < recent["vwap"].iloc[:-1]).any()
        reclaim = float(recent["close"].iloc[-1]) > float(recent["vwap"].iloc[-1])
        return dipped and reclaim
    else:
        spiked = (recent["close"].iloc[:-1] > recent["vwap"].iloc[:-1]).any()
        lost   = float(recent["close"].iloc[-1]) < float(recent["vwap"].iloc[-1])
        return spiked and lost


def _detect_rejection_candle(df5: pd.DataFrame, direction: str, ob: dict) -> bool:
    """Strong rejection candle at OB zone: wick into OB, body closes away."""
    if not ob.get("valid") or len(df5) < 2:
        return False

    last = df5.iloc[-1]
    o, c = float(last["open"]),  float(last["close"])
    h, l = float(last["high"]),  float(last["low"])
    rng  = h - l
    if rng < 1e-9:
        return False

    ob_top = ob.get("body_top", ob.get("high", 0)) or 0
    ob_bot = ob.get("body_bot", ob.get("low",  0)) or 0

    if direction == "LONG":
        wick_into_ob = l <= ob_top          # low dipped into or below OB
        closed_above = c > ob_bot           # closed above OB low
        bullish_body = c > o                # green candle
        body_in_top  = (c - l) / rng > 0.55
        return wick_into_ob and closed_above and bullish_body and body_in_top
    else:
        wick_into_ob = h >= ob_bot
        closed_below = c < ob_top
        bearish_body = c < o
        body_in_bot  = (h - c) / rng > 0.55
        return wick_into_ob and closed_below and bearish_body and body_in_bot


def _detect_5m_structure(df5: pd.DataFrame, direction: str) -> bool:
    """5min confirms bias: LONG → HH + HL over last 5 candles; SHORT → LH + LL."""
    if len(df5) < 6:
        return False
    recent = df5.iloc[-5:]
    highs  = recent["high"].values
    lows   = recent["low"].values
    if direction == "LONG":
        return highs[-1] > highs[-3] and lows[-1] > lows[-3]
    else:
        return highs[-1] < highs[-3] and lows[-1] < lows[-3]


def _detect_volume_signature(df5: pd.DataFrame) -> tuple:
    """Returns (is_spike: bool, ratio: float). Spike = volume >= 1.5x average."""
    if "vol_ma" not in df5.columns or len(df5) == 0:
        return False, 1.0
    last   = df5.iloc[-1]
    vol    = float(last["volume"])
    vol_ma = max(float(last["vol_ma"]) if not np.isnan(last["vol_ma"]) else 1.0, 1.0)
    ratio  = vol / vol_ma
    return ratio >= 1.5, round(ratio, 1)


# ══════════════════════════════════════════════════════════════════
# TRADE PARAMETER BUILDER
# ══════════════════════════════════════════════════════════════════

def _build_trade_params(df5: pd.DataFrame, direction: str,
                        ob: dict, pdh=None, pdl=None) -> dict | None:
    """
    Calculates entry, SL (below OB wick), T1, T2, RR.
    Returns None if SL > 0.8 % or RR < 2.5 (hard rules).
    """
    close = float(df5["close"].iloc[-1])
    entry = round(close, 2)

    if direction == "LONG":
        sl = round(ob["low"] * 0.999, 2)               # just below OB wick
        sl = max(sl, round(entry * (1 - 0.008), 2))    # enforce 0.8 % max
        if sl >= entry:
            sl = round(entry * 0.993, 2)
        sl_pct = round((entry - sl) / entry * 100, 2)
        if sl_pct > 0.8:
            return None

        # T2 = nearest swing high above entry, or PDH
        _, lows_h = [], []
        highs_5m, _ = _find_swings(df5, left=2, right=2)
        candidates   = [h for _, h in highs_5m if h > entry * 1.002]
        t2 = min(candidates) if candidates else round(entry + 3 * (entry - sl), 2)
        if pdh and pdh > entry * 1.002:
            t2 = min(t2, pdh)

    else:  # SHORT
        sl = round(ob["high"] * 1.001, 2)
        sl = min(sl, round(entry * (1 + 0.008), 2))
        if sl <= entry:
            sl = round(entry * 1.007, 2)
        sl_pct = round((sl - entry) / entry * 100, 2)
        if sl_pct > 0.8:
            return None

        _, lows_5m = _find_swings(df5, left=2, right=2)
        candidates  = [l for _, l in lows_5m if l < entry * 0.998]
        t2 = max(candidates) if candidates else round(entry - 3 * (sl - entry), 2)
        if pdl and pdl < entry * 0.998:
            t2 = max(t2, pdl)

    risk   = abs(entry - sl)
    reward = abs(t2 - entry)
    rr     = round(reward / risk, 2) if risk > 0 else 0
    if rr < 2.5:
        return None

    t1 = round(entry + (t2 - entry) * 0.5, 2) if direction == "LONG" \
         else round(entry - (entry - t2) * 0.5, 2)

    return {
        "entry":    entry,
        "sl":       sl,
        "t1":       t1,
        "t2":       t2,
        "rr_ratio": rr,
        "sl_pct":   sl_pct,
    }


# ══════════════════════════════════════════════════════════════════
# MAIN SCORING ENGINE
# ══════════════════════════════════════════════════════════════════

def score_stock(df5: pd.DataFrame, df15: pd.DataFrame, symbol: str,
                pdh=None, pdl=None, ist_time: datetime = None) -> dict:
    """
    SMC + ICT + Price Action scoring.
    Returns full signal dict or {} if blocked / insufficient data.
    """
    if len(df5) < 12 or len(df15) < 8:
        return {}

    # ── Current IST time ──────────────────────────────────────────
    if ist_time is None:
        ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    is_thursday = ist_time.weekday() == 3

    # ── Hard rule: no entries after 14:30 ─────────────────────────
    t = ist_time.hour * 100 + ist_time.minute
    if t >= 1430:
        return {}

    # ── Kill zone check (REQUIRED) ────────────────────────────────
    kill_zone, kz_pts = _get_kill_zone(ist_time.hour, ist_time.minute)
    if kz_pts == 0:        # not in KZ1 / KZ2 / KZ3
        return {}
    if is_thursday and kill_zone != "KZ3":
        return {}

    # ── Prepare indicators ────────────────────────────────────────
    df5  = _vwap(_vol_ma(_rsi(df5.copy())))
    df15 = df15.copy()

    close = float(df5["close"].iloc[-1])
    if close <= 0:
        return {}

    # ════════════════════════════════════════════
    # PHASE 1  —  SMC Structure  (all 3 REQUIRED)
    # ════════════════════════════════════════════

    # 1a. BOS / CHOCH on 15 min
    struct = _detect_bos_choch(df15)
    if not struct["bos"] and not struct["choch"]:
        return {}

    direction = struct["direction"]
    if direction is None:
        return {}

    phase1 = 0
    reasons = []

    if struct["bos"]:
        phase1 += 25
        reasons.append(f"BOS confirmed 15min ({direction})")
    else:
        phase1 += 25
        reasons.append(f"CHOCH reversal 15min ({direction})")

    # 1b. Order Block (REQUIRED)
    ob = _detect_order_block(df15, direction)
    if not ob["valid"]:
        return {}
    phase1 += 20
    reasons.append(f"Unmitigated OB {ob['body_bot']:.1f}–{ob['body_top']:.1f}")

    # 1c. Liquidity Sweep (REQUIRED)
    swept, sweep_lvl = _detect_liquidity_sweep(df5, direction, pdh, pdl)
    if not swept:
        return {}
    phase1 += 15
    reasons.append(f"Liquidity sweep at {sweep_lvl:.1f}")

    # ════════════════════════════════════════════
    # PHASE 2  —  ICT Time & Price
    # ════════════════════════════════════════════

    phase2 = kz_pts   # +15 for valid kill zone
    reasons.append(f"Kill Zone {kill_zone} active (+{kz_pts}pts)")

    if _detect_ote(df5, direction):
        phase2 += 10
        reasons.append("OTE zone 61.8–79 % fibonacci")

    fvg = _detect_fvg(df5, direction)
    if fvg["valid"]:
        phase2 += 8
        reasons.append(f"FVG imbalance {fvg['bot']:.1f}–{fvg['top']:.1f}")

    # PDH/PDL sweep + reclaim bonus
    if sweep_lvl:
        if direction == "LONG" and pdl and abs(sweep_lvl - pdl) / pdl < 0.003:
            phase2 += 7
            reasons.append("PDL sweep + reclaim")
        elif direction == "SHORT" and pdh and abs(sweep_lvl - pdh) / pdh < 0.003:
            phase2 += 7
            reasons.append("PDH sweep + reclaim")

    # ════════════════════════════════════════════
    # PHASE 3  —  Price Action Confirmation
    # ════════════════════════════════════════════

    phase3 = 0

    if _detect_rejection_candle(df5, direction, ob):
        phase3 += 10
        reasons.append("Strong rejection candle at OB")

    if _detect_5m_structure(df5, direction):
        phase3 += 7
        reasons.append("5min HH/HL (or LH/LL) aligns with 15min bias")

    if _detect_vwap_reclaim(df5, direction):
        phase3 += 5
        reasons.append("VWAP reclaim confirmed")

    vol_sig, vol_ratio = _detect_volume_signature(df5)
    if vol_sig:
        phase3 += 5
        reasons.append(f"Volume {vol_ratio}x spike at reaction zone")

    # ════════════════════════════════════════════
    # PHASE 4  —  Confluence Boosters
    # ════════════════════════════════════════════

    phase4 = 0
    last5  = df5.iloc[-1]
    vwap   = float(last5.get("vwap", close))
    rsi_v  = float(last5["rsi"]) if "rsi" in last5.index and not np.isnan(last5["rsi"]) else 50.0

    # Round number confluence (nearest 50 or 100)
    rnd50  = round(close / 50)  * 50
    rnd100 = round(close / 100) * 100
    if abs(close - rnd50)  / close < 0.003 \
    or abs(close - rnd100) / close < 0.003:
        phase4 += 5
        reasons.append("Round number confluence")

    # OB aligns with PDH / PDL daily S&R
    if ob["valid"] and pdh and pdl:
        if direction == "LONG"  and abs(ob["body_bot"] - pdl) / pdl < 0.005:
            phase4 += 5
            reasons.append("OB at daily S&R (PDL)")
        elif direction == "SHORT" and abs(ob["body_top"] - pdh) / pdh < 0.005:
            phase4 += 5
            reasons.append("OB at daily S&R (PDH)")

    # RSI 40–65 at entry (not overbought/oversold)
    if 40 <= rsi_v <= 65:
        phase4 += 3
        reasons.append(f"RSI {rsi_v:.0f} — ideal entry zone (40–65)")

    # ════════════════════════════════════════════
    # TOTAL & SIGNAL STRENGTH
    # ════════════════════════════════════════════

    total = phase1 + phase2 + phase3 + phase4
    if total < 65:
        return {}

    # ── Trade parameters — hard rules ─────────────────────────────
    params = _build_trade_params(df5, direction, ob, pdh, pdl)
    if params is None:
        return {}    # SL too wide OR RR < 2.5

    pct = round(total / 150 * 100, 1)
    if total >= 100:
        strength = "EXCELLENT"
    elif total >= 80:
        strength = "GOOD"
    else:
        strength = "WEAK"

    return {
        # ── Identity ───────────────────────────────────────────────
        "symbol":    symbol,
        "direction": direction,
        "signal":    "BUY" if direction == "LONG" else "SELL",

        # ── Score ──────────────────────────────────────────────────
        "score":           total,
        "score_pct":       pct,
        "signal_strength": strength,
        "blocked_reason":  None,
        "kill_zone":       kill_zone,

        "phase_scores": {
            "smc_structure":  phase1,
            "ict_time_price": phase2,
            "price_action":   phase3,
            "boosters":       phase4,
        },

        "must_have_checklist": {
            "bos_or_choch_15min": struct["bos"] or struct["choch"],
            "order_block_valid":  ob["valid"],
            "liquidity_sweep":    swept,
            "inside_kill_zone":   kz_pts > 0,
        },

        "trade_params": params,

        # ── Flat aliases (backward-compat with notifier / logger) ──
        "entry":     params["entry"],
        "target":    params["t2"],
        "t1":        params["t1"],
        "t2":        params["t2"],
        "sl":        params["sl"],
        "rr":        params["rr_ratio"],

        # ── Meta ───────────────────────────────────────────────────
        "reasons":   reasons,
        "rsi":       round(rsi_v, 1),
        "vwap":      round(vwap, 2),
        "vol_ratio": vol_ratio,
        "confidence": strength,
    }
