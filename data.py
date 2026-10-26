"""
Market data helpers shared by the backtest and the alerts.
Prices come from Yahoo Finance; all timestamps are converted to Indian time (IST).
"""
from pathlib import Path

import pandas as pd

import config

IST = "Asia/Kolkata"


def _clean(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    idx = df.index
    df.index = idx.tz_convert(IST).tz_localize(None) if idx.tz is not None else idx
    return df.sort_index()


def load_yahoo(ticker: str, period: str = "60d", interval: str = "5m") -> pd.DataFrame:
    import yfinance as yf

    return _clean(yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False))


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = "datetime" if "datetime" in df.columns else df.columns[0]
    df[tcol] = pd.to_datetime(df[tcol])
    if df[tcol].dt.tz is not None:
        df[tcol] = df[tcol].dt.tz_convert(IST).dt.tz_localize(None)
    return df.set_index(tcol)[["open", "high", "low", "close"]].sort_index()


def load(key: str, inst: dict, csv_dir: str = None, period: str = "60d") -> pd.DataFrame:
    """Candles for one instrument, from <csv_dir>/<KEY>.csv if given, otherwise Yahoo."""
    if csv_dir:
        f = Path(csv_dir) / f"{key}.csv"
        return load_csv(str(f)) if f.exists() else pd.DataFrame(columns=["open", "high", "low", "close"])
    return load_yahoo(inst["ticker"], period=period)


def india_vix(csv_dir: str = None) -> float:
    """Latest India VIX (annual volatility in %), used to estimate index option prices."""
    try:
        if csv_dir:
            raise RuntimeError("offline")
        v = load_yahoo("^INDIAVIX", period="5d", interval="1d")["close"].dropna()
        return float(v.iloc[-1]) if len(v) else config.INDIA_VIX_FALLBACK
    except Exception:
        return config.INDIA_VIX_FALLBACK


def usdinr_series(csv_dir: str = None) -> pd.Series:
    """Daily USD/INR closes indexed by date (for converting commodity prices to rupees)."""
    try:
        if csv_dir:
            raise RuntimeError("offline")
        import yfinance as yf

        fx = _clean(yf.download("USDINR=X", period="90d", interval="1d", progress=False, auto_adjust=False))["close"]
        fx.index = fx.index.date
        return fx
    except Exception:
        return pd.Series(dtype=float)


def usdinr_on(fx: pd.Series, d) -> float:
    if fx is None or fx.empty:
        return config.USDINR_FALLBACK
    earlier = fx[fx.index <= d]
    return float(earlier.iloc[-1]) if len(earlier) else float(fx.iloc[0])
