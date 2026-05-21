"""
NSE Intraday Strategy  —  Dual-Direction Multi-Confluence
=========================================================
Scores LONG and SHORT independently, picks whichever scores higher.
Fixes the direction-locking bug where Supertrend lag blocked SHORT signals.

7 Signals:
  1. Supertrend  5m + 15m        max 2.5 pts
  2. ORB Breakout / Breakdown    max 2.0 pts
  3. VWAP position               max 1.5 pts
  4. EMA 9/21 stack  5m + 15m   max 1.5 pts
  5. RSI momentum zone           max 1.0 pts
  6. Volume vs average           max 1.0 pts
  7. PDH / PDL breakout bonus    max 0.5 pts

Total: 10 pts
ALERT    : score >= 6.5   (strong setup — trade it)
WATCHLIST: score >= 5.0   (setup forming — watch closely)
"""

import pandas as pd
import numpy as np


# ── INDICATORS ─────────────────────────────────────────────────

def _supertrend(df: pd.DataFrame, period=10, mult=3.0) -> pd.DataFrame:
    hl2 = (df["high"] + df["low"]) / 2
    prev_c = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_c).abs(),
        (df["low"]  - prev_c).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    st   = np.full(len(df), np.nan)
    dir_ = np.zeros(len(df), dtype=int)

    for i in range(1, len(df)):
        c = df["close"].iloc[i]
        prev_st = st[i - 1]

        if np.isnan(prev_st):
            st[i]   = lower.iloc[i]
            dir_[i] = 1
        elif prev_st <= upper.iloc[i - 1]:   # was bullish
            if c < lower.iloc[i]:
                st[i]   = upper.iloc[i]
                dir_[i] = -1
            else:
                st[i]   = lower.iloc[i]
                dir_[i] = 1
        else:                                 # was bearish
            if c > upper.iloc[i]:
                st[i]   = lower.iloc[i]
                dir_[i] = 1
            else:
                st[i]   = upper.iloc[i]
                dir_[i] = -1

    df = df.copy()
    df["st_dir"] = dir_
    return df


def _vwap(df: pd.DataFrame) -> pd.DataFrame:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df = df.copy()
    df["vwap"] = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
    return df


def _emas(df: pd.DataFrame, periods=(9, 21)) -> pd.DataFrame:
    df = df.copy()
    for p in periods:
        df[f"ema{p}"] = df["close"].ewm(span=p, adjust=False).mean()
    return df


def _rsi(df: pd.DataFrame, period=14) -> pd.DataFrame:
    d    = df["close"].diff()
    gain = d.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs   = gain / loss.replace(0, np.nan)
    df   = df.copy()
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def _orb(df: pd.DataFrame, minutes=15) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = df.index[0] + pd.Timedelta(minutes=minutes)
    orb    = df[df.index <= cutoff]
    df     = df.copy()
    df["orb_high"] = orb["high"].max()
    df["orb_low"]  = orb["low"].min()
    return df


def _vol_ma(df: pd.DataFrame, period=20) -> pd.DataFrame:
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(period, min_periods=5).mean()
    return df


# ── SCORE ONE DIRECTION ────────────────────────────────────────

def _score_direction(l5, p5, l15, direction: str,
                     pdh=None, pdl=None) -> tuple:
    """Returns (score, reasons_list) for a single direction."""
    score   = 0.0
    reasons = []
    close   = float(l5["close"])

    bull = (direction == "LONG")

    # ── 1. Supertrend (2.5 pts max) ───────────────────────────
    st5_agree  = (int(l5["st_dir"])  ==  1) if bull else (int(l5["st_dir"])  == -1)
    st15_agree = (int(l15["st_dir"]) ==  1) if bull else (int(l15["st_dir"]) == -1)

    if st5_agree and st15_agree:
        score += 2.5
        reasons.append(f"Supertrend {'BULLISH' if bull else 'BEARISH'} (5m+15m)")
    elif st5_agree:
        score += 1.5
        reasons.append(f"Supertrend {'BULLISH' if bull else 'BEARISH'} on 5m")
    elif st15_agree:
        score += 1.0
        reasons.append(f"Supertrend {'BULLISH' if bull else 'BEARISH'} on 15m")
    else:
        score -= 1.0    # Supertrend opposing — penalty, not blocker

    # ── 2. ORB (2.0 pts max) ──────────────────────────────────
    orb_h   = float(l5["orb_high"])
    orb_l   = float(l5["orb_low"])
    prev_c  = float(p5["close"])

    if bull:
        if close > orb_h and prev_c <= orb_h:
            score += 2.0; reasons.append("ORB Breakout (fresh)")
        elif close > orb_h:
            score += 1.0; reasons.append("Above ORB High")
        elif close < orb_l:
            score -= 0.5  # price in opposite zone — penalty
    else:
        if close < orb_l and prev_c >= orb_l:
            score += 2.0; reasons.append("ORB Breakdown (fresh)")
        elif close < orb_l:
            score += 1.0; reasons.append("Below ORB Low")
        elif close > orb_h:
            score -= 0.5

    # ── 3. VWAP (1.5 pts max) ─────────────────────────────────
    vwap = float(l5["vwap"])
    if bull:
        if close > vwap * 1.001:
            score += 1.5; reasons.append(f"Above VWAP ({vwap:.1f})")
        elif abs(close - vwap) / vwap < 0.001:
            score += 0.5; reasons.append(f"At VWAP ({vwap:.1f})")
    else:
        if close < vwap * 0.999:
            score += 1.5; reasons.append(f"Below VWAP ({vwap:.1f})")
        elif abs(close - vwap) / vwap < 0.001:
            score += 0.5; reasons.append(f"At VWAP ({vwap:.1f})")

    # ── 4. EMA stack (1.5 pts max) ────────────────────────────
    ema9_5   = float(l5["ema9"])
    ema21_5  = float(l5["ema21"])
    ema9_15  = float(l15["ema9"])
    ema20_15 = float(l15["ema20"])

    ema5_agree  = (ema9_5  > ema21_5)  if bull else (ema9_5  < ema21_5)
    ema15_agree = (ema9_15 > ema20_15) if bull else (ema9_15 < ema20_15)

    if ema5_agree and ema15_agree:
        score += 1.5
        reasons.append(f"EMA stack {'bullish' if bull else 'bearish'} (5m+15m)")
    elif ema5_agree:
        score += 0.8
        reasons.append(f"EMA {'bullish' if bull else 'bearish'} on 5m")
    elif ema15_agree:
        score += 0.5

    # ── 5. RSI zone (1.0 pt max) ──────────────────────────────
    rsi = float(l5["rsi"]) if not np.isnan(l5["rsi"]) else 50.0
    if bull:
        if 55 <= rsi <= 75:
            score += 1.0; reasons.append(f"RSI {rsi:.0f} bullish zone")
        elif 48 <= rsi < 55:
            score += 0.4
        elif rsi > 80:
            score -= 0.5  # overbought penalty
    else:
        if 25 <= rsi <= 45:
            score += 1.0; reasons.append(f"RSI {rsi:.0f} bearish zone")
        elif 45 < rsi <= 52:
            score += 0.4
        elif rsi < 20:
            score -= 0.5  # oversold penalty on short

    # ── 6. Volume (1.0 pt max) ────────────────────────────────
    vol    = float(l5["volume"])
    vol_ma = max(float(l5["vol_ma"]) if not np.isnan(l5["vol_ma"]) else 1.0, 1.0)
    vol_r  = vol / vol_ma

    if vol_r >= 2.0:
        score += 1.0; reasons.append(f"Volume {vol_r:.1f}x spike")
    elif vol_r >= 1.5:
        score += 0.7; reasons.append(f"Volume {vol_r:.1f}x above avg")
    elif vol_r >= 1.0:
        score += 0.3
    # below average volume = 0 pts (no penalty)

    # ── 7. PDH / PDL bonus (0.5 pt) ───────────────────────────
    if pdh and bull and close > pdh:
        score += 0.5; reasons.append(f"Above PDH {pdh:.1f}")
    if pdl and not bull and close < pdl:
        score += 0.5; reasons.append(f"Below PDL {pdl:.1f}")

    return round(max(score, 0.0), 1), reasons


# ── MAIN ENTRY POINT ───────────────────────────────────────────

def score_stock(df5: pd.DataFrame, df15: pd.DataFrame, symbol: str,
                pdh=None, pdl=None) -> dict:
    """
    Score stock for LONG and SHORT independently.
    Returns the better direction if score >= 5.0 else {}.
    """
    if len(df5) < 10 or len(df15) < 4:
        return {}

    # Prepare indicators
    df5  = _supertrend(_vwap(_emas(_rsi(_orb(_vol_ma(df5.copy()))))))
    df15 = _supertrend(_emas(df15.copy(), (9, 20)))

    l5  = df5.iloc[-1]
    p5  = df5.iloc[-2] if len(df5) > 1 else df5.iloc[-1]
    l15 = df15.iloc[-1]

    long_score,  long_reasons  = _score_direction(l5, p5, l15, "LONG",  pdh, pdl)
    short_score, short_reasons = _score_direction(l5, p5, l15, "SHORT", pdh, pdl)

    # Pick better direction
    if long_score >= short_score:
        direction, score, reasons = "LONG",  long_score,  long_reasons
    else:
        direction, score, reasons = "SHORT", short_score, short_reasons

    if score < 5.0 or not reasons:
        return {}

    close = float(l5["close"])
    vwap  = float(l5["vwap"])
    rsi   = float(l5["rsi"]) if not np.isnan(l5["rsi"]) else 50.0
    vol   = float(l5["volume"])
    vol_ma= max(float(l5["vol_ma"]) if not np.isnan(l5["vol_ma"]) else 1.0, 1.0)

    # ATR-based SL/TP
    atr = float((df5["high"] - df5["low"]).ewm(span=14, adjust=False).mean().iloc[-1])
    atr = max(atr, close * 0.002)

    if direction == "LONG":
        entry  = round(close, 2)
        sl     = round(close - 1.5 * atr, 2)
        target = round(close + 3.0 * atr, 2)
    else:
        entry  = round(close, 2)
        sl     = round(close + 1.5 * atr, 2)
        target = round(close - 3.0 * atr, 2)

    risk   = abs(entry - sl)
    reward = abs(target - entry)
    rr     = round(reward / risk, 2) if risk > 0 else 0

    # Confidence label
    if score >= 8.0:
        confidence = "VERY HIGH"
    elif score >= 6.5:
        confidence = "HIGH"
    else:
        confidence = "MODERATE"

    return {
        "symbol":     symbol,
        "direction":  direction,
        "score":      score,
        "confidence": confidence,
        "entry":      entry,
        "target":     target,
        "sl":         sl,
        "rr":         rr,
        "reasons":    reasons,
        "rsi":        round(rsi, 1),
        "vwap":       round(vwap, 2),
        "vol_ratio":  round(vol / vol_ma, 1),
    }
