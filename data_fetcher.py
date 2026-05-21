import yfinance as yf
import pandas as pd


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns that newer yfinance versions return."""
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower().strip() for c in df.columns]
    df = df[~df.index.duplicated(keep="last")]
    return df.dropna()


def get_intraday_data(symbol: str, interval: str = "5m") -> pd.DataFrame:
    ticker = f"{symbol}.NS"
    try:
        df = yf.download(ticker, period="5d", interval=interval,
                         progress=False, auto_adjust=True)
        df = _clean(df)
        if df.empty:
            return df

        df.index = pd.to_datetime(df.index)

        # Convert UTC → IST (UTC+5:30)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata")
        else:
            df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")

        # Keep only NSE market hours in IST
        df = df.between_time("09:15", "15:30")

        # Remove timezone info for simplicity downstream
        df.index = df.index.tz_localize(None)

        # Try today first; fall back to last available trading day
        import datetime
        today = datetime.date.today()
        today_df = df[df.index.date == today]
        if len(today_df) >= 5:
            return today_df

        # Market closed / weekend — use last available trading day
        available_dates = sorted(set(df.index.date), reverse=True)
        for d in available_dates:
            day_df = df[df.index.date == d]
            if len(day_df) >= 5:
                return day_df

        return pd.DataFrame()
    except Exception as e:
        print(f"  [data] {symbol} {interval}: {e}")
        return pd.DataFrame()


def get_prev_day_high_low(symbol: str):
    """Return (prev_high, prev_low) for PDH/PDL breakout filter."""
    ticker = f"{symbol}.NS"
    try:
        df = yf.download(ticker, period="5d", interval="1d",
                         progress=False, auto_adjust=True)
        df = _clean(df)
        if len(df) < 2:
            return None, None
        prev = df.iloc[-2]
        return float(prev["high"]), float(prev["low"])
    except Exception:
        return None, None
