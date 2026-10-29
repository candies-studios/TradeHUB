"""
Rule-based intraday setups on 5-minute candles:

  ORB   ORB-5M      Opening Range Breakout + retest
  VWAP  VWAP-5M     VWAP / 20 EMA pullback with 15-minute trend and ADX filters
  PDH   PDH-PDL-5M  Previous-session high / low breakout + retest

Each setup has an entry, a stop-loss beyond the retest/pullback swing and a 3R target,
all as prices of the underlying (index or commodity). backtest.py and live_alerts.py
both call find_setups(), so alerts and backtests always follow exactly the same rules.

"Session" always means the instrument's own exchange session from config.INSTRUMENTS
(NSE/BSE 09:15-15:30, MCX 09:00-23:30), never the calendar day.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

import config
import strategy

CANDLE = timedelta(minutes=5)


# ---------------- indicators ----------------
def adx(d: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's ADX."""
    up, dn = d["high"].diff(), -d["low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=d.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=d.index)
    prev = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - prev).abs(), (d["low"] - prev).abs()], axis=1).max(axis=1)
    a = 1 / n
    atr_ = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=a, adjust=False).mean() / atr_
    mdi = 100 * minus.ewm(alpha=a, adjust=False).mean() / atr_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean()


def prepare(df: pd.DataFrame, inst: dict) -> pd.DataFrame:
    """Session-only 5-minute candles with every indicator the three strategies need."""
    if df.empty:
        return df
    d = df[[strategy.in_session(ts, inst) for ts in df.index]].copy()
    if d.empty:
        return d
    if "volume" not in d:
        d["volume"] = 0.0
    d["session"] = d.index.date
    d["ema20"] = d["close"].ewm(span=20, adjust=False).mean()
    d["atr"] = strategy.atr(d)
    d["adx"] = adx(d)
    d["adx_prev"] = d["adx"].shift(1)

    # Session VWAP, reset every session. The free feed has no volume for Indian indices,
    # so for them this is an equal-weighted session average of the typical price.
    tp = (d["high"] + d["low"] + d["close"]) / 3
    vol = d["volume"].fillna(0).clip(lower=0)
    has_vol = vol.groupby(d["session"]).transform("sum") > 0
    w = pd.Series(np.where(has_vol, vol, 1.0), index=d.index)
    d["vwap"] = (tp * w).groupby(d["session"]).cumsum() / w.groupby(d["session"]).cumsum()

    # 15-minute 20 EMA trend filter, using only 15-minute candles that have already closed.
    h = d[["open", "high", "low", "close"]].resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    h["ema20_15"] = h["close"].ewm(span=20, adjust=False).mean()
    h = h.assign(avail=h.index + timedelta(minutes=15)).rename(columns={"close": "close_15"})
    left = pd.DataFrame({"avail": d.index + CANDLE})
    m = pd.merge_asof(left, h[["avail", "close_15", "ema20_15"]], on="avail", direction="backward")
    d["close_15"] = m["close_15"].to_numpy()
    d["ema20_15"] = m["ema20_15"].to_numpy()

    # Previous COMPLETED session's high/low, and the highest high / lowest low of the 5 sessions before.
    s = d.groupby("session").agg(hi=("high", "max"), lo=("low", "min"))
    s["pdh"], s["pdl"] = s["hi"].shift(1), s["lo"].shift(1)
    s["hi5"] = s["hi"].shift(1).rolling(5, min_periods=1).max()
    s["lo5"] = s["lo"].shift(1).rolling(5, min_periods=1).min()
    return d.join(s[["pdh", "pdl", "hi5", "lo5"]], on="session")


# ---------------- helpers ----------------
def _ok(x) -> bool:
    return x is not None and x == x


def _beyond(price, level, sgn) -> bool:
    """price is on the trade's side of level (above for longs, below for shorts)."""
    return sgn * (price - level) > 0


def _bull(r, sgn) -> bool:
    return sgn * (r.close - r.open) > 0


def _touch(r, level, sgn, tol) -> bool:
    """Candle came back to the level (from above for longs, from below for shorts)."""
    return r.low <= level + tol if sgn > 0 else r.high >= level - tol


def _make(r, side, entry_type, entry, stop, atr, inst, **extra):
    """Build a setup; None if the stop is on the wrong side or too far away relative to ATR."""
    sgn = 1 if side == "CE" else -1
    risk = sgn * (entry - stop)
    if not (_ok(atr) and atr > 0 and risk > 0 and risk <= config.MAX_RISK_ATR * atr):
        return None
    close_time = r.Index + CANDLE
    if not strategy.in_entry_window(close_time, inst):
        return None
    return dict(time=r.Index, close_time=close_time, side=side, entry_type=entry_type,
                entry=float(entry), stop=float(stop), target=float(entry + sgn * config.REWARD_R * risk),
                risk=float(risk), atr=float(atr),
                valid_until=close_time + CANDLE * (config.ENTRY_VALID_CANDLES if entry_type == "stop" else 0),
                **extra)


def _swing(rows, a, b, sgn):
    seg = rows[a:b + 1]
    return min(x.low for x in seg) if sgn > 0 else max(x.high for x in seg)


# ---------------- ORB-5M ----------------
def _orb_side(rows, n_or, level, side, inst):
    sgn = 1 if side == "CE" else -1
    state, brk_i, rt_i = "break", None, None
    for i in range(n_or, len(rows)):
        r = rows[i]
        atr = r.atr
        if not _ok(atr) or atr <= 0:
            continue
        if (r.Index + CANDLE).time() > strategy.t(inst["entry"][1]):
            return None                                 # entry window over for today
        tol, inside = config.RETEST_TOL_ATR * atr, config.INSIDE_CLOSE_ATR * atr
        if state == "break":
            # 2-3. a candle CLOSES beyond the opening range, above/below VWAP, the 20 EMA and the 15-min trend
            if _beyond(r.close, level, sgn):
                if sgn * (r.close - level) > config.ORB_MAX_BREAKOUT_ATR * atr:
                    return None                         # already travelled too far: skip this direction
                trend = _ok(r.close_15) and _ok(r.ema20_15) and _beyond(r.close_15, r.ema20_15, sgn)
                if _beyond(r.close, r.vwap, sgn) and _beyond(r.close, r.ema20, sgn) and trend:
                    state, brk_i = "retest", i
            continue
        if sgn * (level - r.close) > inside:            # closed decisively back inside the range
            return None
        if state == "retest":
            if i - brk_i > config.RETEST_MAX_CANDLES:
                return None
            if i > brk_i and _touch(r, level, sgn, tol):  # 4. retest of the broken level
                state, rt_i = "confirm", i
            continue
        if state == "confirm":
            if i - rt_i > config.CONFIRM_MAX_CANDLES:
                return None
            rt = rows[rt_i]
            # 5. bullish (bearish) confirmation candle closes beyond the retest candle's high (low)
            if (_bull(r, sgn) and _beyond(r.close, rt.high if sgn > 0 else rt.low, sgn)
                    and _beyond(r.close, r.vwap, sgn) and _beyond(r.close, r.ema20, sgn)):
                stop = _swing(rows, rt_i, i, sgn) - sgn * config.STOP_BUFFER_ATR * atr
                return _make(r, side, "close", r.close, stop, atr, inst, level=float(level))
            if _touch(r, level, sgn, tol):             # deeper retest: this candle becomes the retest
                rt_i = i
    return None


def orb(d: pd.DataFrame, inst: dict):
    out, n_or = [], max(1, config.ORB_MINUTES // 5)
    for _, g in d.groupby("session"):
        if len(g) <= n_or:
            continue
        rows = list(g.itertuples())
        orh, orl = max(x.high for x in rows[:n_or]), min(x.low for x in rows[:n_or])   # 1. opening range
        for side, level in (("CE", orh), ("PE", orl)):                                # one attempt per direction
            s = _orb_side(rows, n_or, level, side, inst)
            if s:
                out.append(s)
    return out


# ---------------- VWAP-5M ----------------
def _blocked_by_level(s, levels) -> bool:
    """True if a major level sits between entry and SR_BLOCK_R x risk in the trade's direction."""
    sgn = 1 if s["side"] == "CE" else -1
    reach = s["entry"] + sgn * config.SR_BLOCK_R * s["risk"]
    return any(_ok(L) and sgn * (L - s["entry"]) > 0 and sgn * (reach - L) > 0 for L in levels)


def vwap_pullback(d: pd.DataFrame, inst: dict):
    """Trend leg first (15-min trend, ADX above the minimum and rising, price beyond VWAP and EMA20),
    then a pullback into the VWAP / EMA20 zone that holds the last swing, then a confirmation candle."""
    out = []
    lb = config.VWAP_SWING_LOOKBACK
    for _, g in d.groupby("session"):
        rows = list(g.itertuples())
        pending, count = {"CE": None, "PE": None}, 0
        for i in range(2, len(rows)):
            if count >= config.VWAP_MAX_ENTRIES:
                break
            r = rows[i]
            atr = r.atr
            if not (_ok(atr) and atr > 0 and _ok(r.adx)):
                continue
            tol = config.RETEST_TOL_ATR * atr
            for side in ("CE", "PE"):
                sgn = 1 if side == "CE" else -1
                htf = _ok(r.close_15) and _ok(r.ema20_15) and _beyond(r.close_15, r.ema20_15, sgn)
                zone = max(r.vwap, r.ema20) if sgn > 0 else min(r.vwap, r.ema20)
                pb = pending[side]
                if pb is None:
                    # 1-4. a trending candle (beyond VWAP + EMA20, ADX above minimum and rising) in the last
                    #      few candles, and now price pulls back to the zone without breaking the last swing
                    leg = any(_ok(x.adx) and _ok(x.adx_prev) and x.adx > config.VWAP_ADX_MIN and x.adx > x.adx_prev
                              and _beyond(x.close, x.vwap, sgn) and _beyond(x.close, x.ema20, sgn)
                              for x in rows[max(0, i - config.VWAP_TREND_LOOKBACK):i])
                    if htf and leg and _touch(r, zone, sgn, tol):
                        ref = _swing(rows, max(0, i - lb), i - 1, sgn)
                        if _beyond(r.low if sgn > 0 else r.high, ref, sgn):
                            pending[side] = {"i": i, "ref": ref}
                    continue
                if i - pb["i"] > config.CONFIRM_MAX_CANDLES or not _beyond(r.low if sgn > 0 else r.high, pb["ref"], sgn):
                    pending[side] = None                 # took too long, or broke the swing
                    continue
                # 5. bullish candle closes back beyond the pullback zone, trend still valid; 6. enter beyond its high
                if htf and r.adx > config.VWAP_ADX_MIN and _bull(r, sgn) and _beyond(r.close, zone, sgn):
                    stop = _swing(rows, pb["i"], i, sgn) - sgn * config.VWAP_STOP_BUFFER_ATR * atr
                    s = _make(r, side, "stop", r.high if sgn > 0 else r.low, stop, atr, inst)
                    if s and not _blocked_by_level(s, (r.pdh, r.pdl)):
                        out.append(s)
                        count += 1
                    pending[side] = None
                elif _touch(r, zone, sgn, tol) and _beyond(r.low if sgn > 0 else r.high, pb["ref"], sgn):
                    pb["i"] = i                          # still pulling back: wait for the confirmation
    return out


# ---------------- PDH-PDL-5M ----------------
def _pdh_side(rows, level, nxt, side, inst):
    sgn = 1 if side == "CE" else -1
    state, brk_i, rt_i = "break", None, None
    for i in range(len(rows)):
        r = rows[i]
        atr = r.atr
        if not _ok(atr) or atr <= 0:
            continue
        if (r.Index + CANDLE).time() > strategy.t(inst["entry"][1]):
            return None
        tol, inside = config.RETEST_TOL_ATR * atr, config.INSIDE_CLOSE_ATR * atr
        if state == "break":
            if _beyond(r.close, level, sgn):            # 1-2. a 5-minute candle closes beyond the level
                state, brk_i = "retest", i
            continue
        if sgn * (level - r.close) > inside:            # failed to hold the level
            return None
        if state == "retest":
            if i - brk_i > config.RETEST_MAX_CANDLES:
                return None
            if i > brk_i and _touch(r, level, sgn, tol):
                state, rt_i = "confirm", i              # 3. retest of the level
            else:
                continue
        if state == "confirm":
            if i - rt_i > config.CONFIRM_MAX_CANDLES:
                return None
            # 3-5. holds the level, beyond VWAP and EMA20, bullish (bearish) confirmation candle
            if (_bull(r, sgn) and _beyond(r.close, level, sgn)
                    and _beyond(r.close, r.vwap, sgn) and _beyond(r.close, r.ema20, sgn)):
                stop = _swing(rows, rt_i, i, sgn) - sgn * config.STOP_BUFFER_ATR * atr
                s = _make(r, side, "stop", r.high if sgn > 0 else r.low, stop, atr, inst, level=float(level))
                if s and _ok(nxt) and sgn * (nxt - s["entry"]) > 0 and sgn * (nxt - s["entry"]) < config.PDH_NEXT_LEVEL_R * s["risk"]:
                    return None                         # next major level too close for enough reward
                return s
            if i > rt_i and _touch(r, level, sgn, tol):
                rt_i = i
    return None


def pdh_pdl(d: pd.DataFrame, inst: dict):
    out = []
    for _, g in d.groupby("session"):
        rows = list(g.itertuples())
        first = rows[0]
        if not (_ok(first.pdh) and _ok(first.pdl)):
            continue                                    # need a completed previous session
        nxt_up = first.hi5 if _ok(first.hi5) and first.hi5 > first.pdh else None
        nxt_dn = first.lo5 if _ok(first.lo5) and first.lo5 < first.pdl else None
        for side, level, nxt in (("CE", first.pdh, nxt_up), ("PE", first.pdl, nxt_dn)):
            s = _pdh_side(rows, level, nxt, side, inst)   # one attempt per level per direction
            if s:
                out.append(s)
    return out


FINDERS = {"ORB": orb, "VWAP": vwap_pullback, "PDH": pdh_pdl}


def find_setups(d: pd.DataFrame, inst: dict, strat: str):
    """All setups for one strategy, sorted by time. `d` comes from prepare()."""
    if d.empty:
        return []
    return sorted(FINDERS[strat](d, inst), key=lambda s: s["time"])


def worth_it(s: dict, inst: dict, delta: float, qf: float) -> bool:
    """Skip setups whose 3R reward would be eaten up by brokerage and charges."""
    reward_rs = delta * config.REWARD_R * s["risk"] * qf * inst["units_per_lot"] * inst["lots"]
    return reward_rs >= config.MIN_REWARD_COST_MULT * inst["cost_rs"]
