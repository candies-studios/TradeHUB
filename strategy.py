"""
Shared strategy logic: RSI, signals, strike and expiry selection.
Used by both backtest.py and live_alerts.py so they always agree.
"""
from datetime import date, datetime, time, timedelta

import pandas as pd

import config


def wilder_rsi(close: pd.Series, period: int = config.RSI_PERIOD) -> pd.Series:
    """RSI using Wilder's smoothing (same method TradingView and most broker charts use)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    rsi[avg_loss == 0] = 100
    return rsi


def levels():
    return config.REVERSAL_LEVELS if config.STRATEGY_MODE == "reversal" else config.MOMENTUM_LEVELS


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Adds 'rsi' and 'signal' columns. signal is 'CE', 'PE' or None, decided at candle CLOSE."""
    df = df.copy()
    df["rsi"] = wilder_rsi(df["close"])
    prev = df["rsi"].shift(1)
    lv = levels()
    call_cross = (prev <= lv["call"]) & (df["rsi"] > lv["call"])
    put_cross = (prev >= lv["put"]) & (df["rsi"] < lv["put"])
    df["signal"] = None
    df.loc[call_cross, "signal"] = "CE"
    df.loc[put_cross, "signal"] = "PE"
    return df


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


FIRST_ENTRY = _t(config.FIRST_ENTRY_TIME)
LAST_ENTRY = _t(config.LAST_ENTRY_TIME)
SQUARE_OFF = _t(config.SQUARE_OFF_TIME)


def _holidays():
    return {date.fromisoformat(d) for d in config.NSE_HOLIDAYS}


def expiry_for(d: date) -> date:
    """The nearest weekly expiry on or after date d (moved earlier if it falls on a holiday)."""
    hol = _holidays()
    days_ahead = (config.EXPIRY_WEEKDAY - d.weekday()) % 7
    exp = d + timedelta(days=days_ahead)
    while exp in hol or exp.weekday() >= 5:
        exp -= timedelta(days=1)
    if exp < d:  # this week's expiry was pulled before today -> use next week's
        return expiry_for(d + timedelta(days=7 - d.weekday()))
    return exp


def is_expiry_day(d: date) -> bool:
    return expiry_for(d) == d


def pick_strike(spot: float, side: str, d: date) -> int:
    """ITM strike on normal days, ATM on expiry day."""
    step = config.STRIKE_STEP
    atm = int(round(spot / step) * step)
    if config.ATM_ON_EXPIRY_DAY and is_expiry_day(d):
        return atm
    shift = step * config.ITM_STRIKES
    return atm - shift if side == "CE" else atm + shift


def delta_for(d: date) -> float:
    return config.DELTA_ATM_EXPIRY if (config.ATM_ON_EXPIRY_DAY and is_expiry_day(d)) else config.DELTA_ITM


def in_entry_window(ts: datetime) -> bool:
    return FIRST_ENTRY <= ts.time() <= LAST_ENTRY
