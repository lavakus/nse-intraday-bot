"""
Swing Trading Strategy — NSE India (5-day Mon–Fri holds)
=========================================================
Scoring  : 100-point scale, minimum 55 to select
Direction: LONG only (only stocks in confirmed uptrend)
Hold     : 5 trading days  (enter Monday open → exit Friday close)
Universe : NIFTY 50 + select NIFTY NEXT 50 liquid stocks

Scoring breakdown
-----------------
Phase 1 – Trend Filter     (REQUIRED — skip if fails)
    Price > 200 EMA                          mandatory
    Price > 50 EMA                           mandatory

Phase 2 – Trend Strength   (40 pts)
    EMA9 > EMA21                             +15
    3 consecutive higher closes              +10
    Price in upper half of 20-day range      +10
    Week close > last week high              + 5

Phase 3 – Momentum         (35 pts)
    RSI 50–68  (ideal entry, not overbought) +15
    Volume ≥ 1.5× 20-day average             +12
    MACD line > Signal line                  + 8

Phase 4 – Entry Zone       (25 pts)
    Pullback within 2% of EMA21              +12
    Breakout above 20-day consolidation      +10
    Inside / narrow range day                + 8
    Price near round number / key level      + 5

Risk rules
----------
    SL  : below recent swing low  OR  3% below entry  (whichever is tighter)
    T1  : +5%  from entry  (book 50%)
    T2  : +10% from entry  (book remaining / exit Friday close)
    Min R:R: 1 : 1.5
    Max SL : 4% of entry price
"""

import numpy as np
import pandas as pd

MIN_SCORE  = 55
MAX_SL_PCT = 0.04    # 4 % max stop loss for swing
MIN_RR     = 1.5     # minimum risk-reward ratio

# ── Watchlist ────────────────────────────────────────────────────
SWING_WATCHLIST = [
    # NIFTY 50
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "AXISBANK", "LT", "HCLTECH", "WIPRO", "SUNPHARMA",
    "MARUTI", "TITAN", "BAJFINANCE", "BAJAJFINSV", "NESTLEIND",
    "ASIANPAINT", "ULTRACEMCO", "TECHM", "POWERGRID", "NTPC",
    "ONGC", "COALINDIA", "TATASTEEL", "JSWSTEEL", "HINDALCO",
    "TATAMOTORS", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT", "DRREDDY",
    "CIPLA", "DIVISLAB", "BRITANNIA", "GRASIM", "ADANIPORTS",
    "TATACONSUM", "APOLLOHOSP", "HDFCLIFE", "SBILIFE", "INDUSINDBK",
    "BPCL", "UPL", "ADANIENT",
    # NIFTY NEXT 50 additions (liquid midcaps)
    "PIDILITIND", "BERGEPAINT", "HAVELLS", "SIEMENS", "ABB",
    "MUTHOOTFIN", "CHOLAFIN", "BANDHANBNK", "FEDERALBNK",
    "CANBK", "PNB", "BANKBARODA",
    "AMBUJACEM", "ACC", "SHREECEM",
    "DMART", "NYKAA", "PAYTM",
    "ZOMATO", "IRCTC", "MOTHERSON",
    "HAL", "BEL", "BHEL", "RVNL",
    "TRENT", "VEDL", "SAIL",
]

# Round number levels checked for confluence
_ROUND_LEVELS_PCT = 0.005   # within 0.5% of round number


# ── Indicator helpers ────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff().dropna()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - 100 / (1 + rs)
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def _macd(series: pd.Series):
    ema12  = _ema(series, 12)
    ema26  = _ema(series, 26)
    line   = ema12 - ema26
    signal = _ema(line, 9)
    return float(line.iloc[-1]), float(signal.iloc[-1])


def _swing_low(df: pd.DataFrame, lookback: int = 10) -> float:
    """Recent swing low over last N candles."""
    return float(df["low"].iloc[-lookback:].min())


def _near_round(price: float) -> bool:
    levels = list(range(100, 10000, 50)) + list(range(10000, 200000, 500))
    return any(abs(price - lvl) / price < _ROUND_LEVELS_PCT for lvl in levels)


# ── Main scorer ──────────────────────────────────────────────────

def score_swing(symbol: str, df: pd.DataFrame) -> dict:
    """
    Score a stock for a 5-day swing trade.
    df must be daily OHLCV with at least 250 rows.
    Returns full signal dict or {} if blocked.
    """
    if df is None or len(df) < 60:
        return {}

    close  = df["close"]
    volume = df["volume"]

    # ── Indicators ──────────────────────────────────────────────
    ema9   = _ema(close, 9)
    ema21  = _ema(close, 21)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)

    c0   = float(close.iloc[-1])
    e9   = float(ema9.iloc[-1])
    e21  = float(ema21.iloc[-1])
    e50  = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])

    # ════════════════════════════════════════
    # PHASE 1 — TREND FILTER (REQUIRED)
    # ════════════════════════════════════════
    if c0 < e200:   # below 200 EMA → skip
        return {}
    if c0 < e50:    # below 50 EMA → skip
        return {}

    score   = 0
    reasons = []

    # ════════════════════════════════════════
    # PHASE 2 — TREND STRENGTH (40 pts)
    # ════════════════════════════════════════

    # EMA9 > EMA21 (+15)
    if e9 > e21:
        score += 15
        reasons.append("EMA9 > EMA21 — short-term uptrend")

    # 3 consecutive higher closes (+10)
    last4 = list(close.iloc[-4:])
    if last4[1] > last4[0] and last4[2] > last4[1] and last4[3] > last4[2]:
        score += 10
        reasons.append("3 consecutive higher closes")

    # Price in upper half of 20-day range (+10)
    high20 = float(df["high"].iloc[-20:].max())
    low20  = float(df["low"].iloc[-20:].min())
    rng20  = high20 - low20
    if rng20 > 0 and (c0 - low20) / rng20 >= 0.5:
        score += 10
        reasons.append(f"Price in upper half of 20-day range ({round((c0-low20)/rng20*100)}%)")

    # This week's close > last week's high (+5)
    if len(df) >= 10:
        last_week_high = float(df["high"].iloc[-10:-5].max())
        if c0 > last_week_high:
            score += 5
            reasons.append(f"Close above last week high ({last_week_high:.1f})")

    # ════════════════════════════════════════
    # PHASE 3 — MOMENTUM (35 pts)
    # ════════════════════════════════════════

    # RSI 50–68 (+15)
    rsi_v = _rsi(close)
    if 50 <= rsi_v <= 68:
        score += 15
        reasons.append(f"RSI {rsi_v:.1f} — ideal swing zone (50–68)")
    elif 68 < rsi_v <= 75:
        score += 7
        reasons.append(f"RSI {rsi_v:.1f} — slightly elevated but trending")

    # Volume ≥ 1.5× 20-day average (+12)
    vol_avg = float(volume.iloc[-21:-1].mean())
    vol_now = float(volume.iloc[-1])
    vol_ratio = round(vol_now / vol_avg, 2) if vol_avg > 0 else 0
    if vol_ratio >= 1.5:
        score += 12
        reasons.append(f"Volume {vol_ratio}× avg — institutional interest")
    elif vol_ratio >= 1.2:
        score += 6
        reasons.append(f"Volume {vol_ratio}× avg — above average")

    # MACD line > Signal line (+8)
    macd_line, macd_sig = _macd(close)
    if macd_line > macd_sig:
        score += 8
        reasons.append("MACD bullish crossover / line above signal")

    # ════════════════════════════════════════
    # PHASE 4 — ENTRY ZONE (25 pts)
    # ════════════════════════════════════════

    # Pullback to EMA21 within 2% (+12)
    pullback_pct = abs(c0 - e21) / e21
    if pullback_pct <= 0.02:
        score += 12
        reasons.append(f"Price within 2% of EMA21 ({e21:.1f}) — ideal pullback entry")
    elif pullback_pct <= 0.04:
        score += 6
        reasons.append(f"Price near EMA21 ({e21:.1f}) — decent pullback")

    # Breakout above 20-day consolidation (+10)
    # (today's close is a new 20-day high)
    prev_high20 = float(df["high"].iloc[-21:-1].max())
    if c0 > prev_high20:
        score += 10
        reasons.append(f"Breakout above 20-day high ({prev_high20:.1f})")

    # Inside bar / narrow range day (+8)
    today_range  = float(df["high"].iloc[-1]) - float(df["low"].iloc[-1])
    avg_range5   = float((df["high"] - df["low"]).iloc[-6:-1].mean())
    if avg_range5 > 0 and today_range < avg_range5 * 0.7:
        score += 8
        reasons.append("Narrow range / inside bar — coiling before move")

    # Round number confluence (+5)
    if _near_round(c0):
        score += 5
        reasons.append(f"Price near round number ({c0:.0f})")

    # ── Threshold check ──────────────────────────────────────────
    if score < MIN_SCORE:
        return {}

    # ── Trade parameters ─────────────────────────────────────────
    swing_sl_price = _swing_low(df, lookback=5)
    sl_pct_from_entry = (c0 - swing_sl_price) / c0

    # If swing low SL is too wide, use fixed 3%
    if sl_pct_from_entry > MAX_SL_PCT or sl_pct_from_entry <= 0:
        swing_sl_price = round(c0 * 0.97, 2)
        sl_pct_from_entry = 0.03

    sl    = round(swing_sl_price, 2)
    risk  = c0 - sl
    t1    = round(c0 + risk * 2.0, 2)   # R:R 1:2 = ~5–6%
    t2    = round(c0 + risk * 3.5, 2)   # R:R 1:3.5 = ~9–12%
    rr_t1 = round(abs(t1 - c0) / risk, 2)
    rr_t2 = round(abs(t2 - c0) / risk, 2)

    if rr_t1 < MIN_RR:
        return {}

    sl_pct = round(sl_pct_from_entry * 100, 2)

    # Signal strength label
    if score >= 85:
        strength = "EXCELLENT"
    elif score >= 70:
        strength = "STRONG"
    else:
        strength = "GOOD"

    return {
        "symbol":          symbol,
        "score":           score,
        "score_pct":       round(score / 100 * 100, 1),
        "signal_strength": strength,
        "direction":       "LONG",
        "entry":           round(c0, 2),
        "sl":              sl,
        "sl_pct":          sl_pct,
        "t1":              t1,
        "t2":              t2,
        "rr_t1":           rr_t1,
        "rr_t2":           rr_t2,
        "rsi":             round(rsi_v, 1),
        "ema21":           round(e21, 2),
        "ema50":           round(e50, 2),
        "ema200":          round(e200, 2),
        "vol_ratio":       vol_ratio,
        "macd_bullish":    macd_line > macd_sig,
        "reasons":         reasons,
        "hold_days":       5,
        "phase_scores": {
            "trend_strength": min(score, 40),
            "momentum":       min(max(score - 40, 0), 35),
            "entry_zone":     min(max(score - 75, 0), 25),
        },
    }
