"""
US Dollar Index (DXY) feed via yfinance.
Symbol: DX-Y.NYB  (NYSE Arca Dollar Index)
Used by Gold strategy for inverse-correlation confirmation.
"""
import yfinance as yf
import pandas as pd

SYMBOL = "DX-Y.NYB"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower().strip() for c in df.columns]
    return df[~df.index.duplicated(keep="last")].dropna()


def get_dxy_data() -> dict:
    """
    Returns DXY bias: bullish / bearish based on EMA stack.
    Gold LONG requires DXY bearish; Gold SHORT requires DXY bullish.
    """
    try:
        df = _clean(yf.download(SYMBOL, period="10d", interval="1h",
                                 progress=False, auto_adjust=True))
        if df.empty or len(df) < 22:
            return _neutral()

        close  = df["close"].astype(float)
        ema9   = float(close.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema21  = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        last_c = float(close.iloc[-1])

        bullish = last_c > ema9 > ema21
        bearish = last_c < ema9 < ema21

        return {
            "close":   round(last_c, 3),
            "ema9":    round(ema9, 3),
            "ema21":   round(ema21, 3),
            "bullish": bullish,
            "bearish": bearish,
            "error":   None,
        }
    except Exception as e:
        return {**_neutral(), "error": str(e)}


def _neutral() -> dict:
    return {"close": None, "ema9": None, "ema21": None,
            "bullish": False, "bearish": False, "error": None}
