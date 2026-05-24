"""
Index data feed — Nifty 50, Bank Nifty, Sensex, India VIX
All data via yfinance (free, no API key needed).
"""
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta

_TICKERS = {
    "NIFTY":    "^NSEI",
    "BANKNIFTY":"^NSEBANK",
    "SENSEX":   "^BSESN",
    "VIX":      "^INDIAVIX",
}

# Strike step sizes
STRIKE_STEP = {
    "NIFTY":     50,
    "BANKNIFTY": 100,
    "SENSEX":    100,
}


def _fetch(yf_sym: str, period: str, interval: str) -> pd.DataFrame | None:
    try:
        df = yf.Ticker(yf_sym).history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df[["open","high","low","close","volume"]].dropna()
    except Exception:
        return None


def get_index_data(index: str) -> dict:
    """
    Returns {price, df_15m, df_5m, change_pct} for Nifty/BankNifty/Sensex.
    """
    sym = _TICKERS[index]
    df_15m = _fetch(sym, "5d", "15m")
    df_5m  = _fetch(sym, "2d",  "5m")

    price = None
    change_pct = None
    try:
        tk    = yf.Ticker(sym)
        info  = tk.fast_info
        price = float(info["last_price"])
        prev  = float(info.get("previous_close") or info["last_price"])
        change_pct = round((price - prev) / prev * 100, 2)
    except Exception:
        if df_15m is not None and not df_15m.empty:
            price = float(df_15m["close"].iloc[-1])

    return {
        "index":      index,
        "price":      price,
        "change_pct": change_pct,
        "df_15m":     df_15m,
        "df_5m":      df_5m,
    }


def get_india_vix() -> dict:
    """Returns India VIX current value and label."""
    try:
        tk  = yf.Ticker("^INDIAVIX")
        vix = float(tk.fast_info["last_price"])
    except Exception:
        vix = 14.0   # fallback neutral

    if vix < 13:
        label = "VERY LOW (cheap options — good to buy)"
        risk  = "low"
    elif vix < 17:
        label = "LOW-MODERATE (good to buy)"
        risk  = "low"
    elif vix < 20:
        label = "MODERATE (normal)"
        risk  = "medium"
    elif vix < 25:
        label = "HIGH (options expensive — reduce size)"
        risk  = "high"
    else:
        label = "VERY HIGH (avoid buying options)"
        risk  = "very_high"

    return {"vix": round(vix, 2), "label": label, "risk": risk,
            "block": vix >= 25}


def nearest_strike(price: float, index: str, direction: str) -> dict:
    """
    Return ATM, OTM, and deep OTM strikes for the given direction.
    direction = 'CALL' or 'PUT'
    """
    step = STRIKE_STEP.get(index, 50)
    atm  = round(price / step) * step

    if direction == "CALL":
        otm1 = atm + step
        otm2 = atm + step * 2
    else:
        otm1 = atm - step
        otm2 = atm - step * 2

    return {"atm": atm, "otm1": otm1, "otm2": otm2, "step": step}


def next_expiry(index: str) -> str:
    """
    Returns the nearest weekly expiry date for the index.
      Nifty     → Thursday
      BankNifty → Wednesday
      Sensex    → Friday
    """
    from datetime import date, timedelta
    expiry_weekday = {"NIFTY": 3, "BANKNIFTY": 2, "SENSEX": 4}
    target = expiry_weekday.get(index, 3)   # default Thursday

    today = date.today()
    days_ahead = target - today.weekday()
    if days_ahead < 0:
        days_ahead += 7
    elif days_ahead == 0:
        # If today IS expiry day, use next week's
        days_ahead = 7

    expiry = today + timedelta(days=days_ahead)
    return expiry.strftime("%d %b %Y")


def get_prev_day_levels(index: str) -> dict:
    """Yesterday's high, low, close — key S/R levels for options."""
    sym = _TICKERS[index]
    try:
        df = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=True)
        df.columns = [c.lower() for c in df.columns]
        if len(df) >= 2:
            yd = df.iloc[-2]
            return {
                "pdh": float(yd["high"]),
                "pdl": float(yd["low"]),
                "pdc": float(yd["close"]),
            }
    except Exception:
        pass
    return {"pdh": None, "pdl": None, "pdc": None}
