"""
Settings for the option-buying strategies (RSI-14, EMA 9/20, ORB-5M, VWAP-5M, PDH-PDL-5M).
Change the numbers here; you don't need to touch the other files.
On GitHub: open this file, click the pencil icon, edit, then "Commit changes".
"""

# ---------------- Strategies ----------------
# Each strategy sends its own alerts (tagged with its name) and is tested separately.
# Set one to False to switch it off.
STRATEGIES = {
    "RSI": True,    # RSI-14 crosses your levels (below)
    "EMA": True,    # 9 EMA crosses the 20 EMA: above = buy CALL, below = buy PUT
    "ORB": True,    # Opening Range Breakout + retest (first 15 minutes)
    "VWAP": True,   # VWAP / 20 EMA pullback with 15-minute trend and ADX filters
    "PDH": True,    # Previous-session high / low breakout + retest
}
STRATEGY_NAMES = {"RSI": "RSI-14", "EMA": "EMA 9/20", "ORB": "ORB-5M", "VWAP": "VWAP-5M", "PDH": "PDH-PDL-5M"}
SETUP_STRATEGIES = ("ORB", "VWAP", "PDH")   # these use price levels for entry, stop-loss and a 3R target
EMA_FAST = 9
EMA_SLOW = 20


def enabled_strategies():
    return [k for k, on in STRATEGIES.items() if on]


# ---------------- ORB-5M / VWAP-5M / PDH-PDL-5M rules ----------------
# Words like "decisively", "too far" and "nearby" in the rules are turned into multiples of
# ATR(14) on the 5-minute chart, so they adapt to each instrument's normal movement.
REWARD_R = 3.0                 # target = 3 x initial risk (3R)
STOP_BUFFER_ATR = 0.10         # stop goes this much ATR beyond the retest / pullback swing
MAX_RISK_ATR = 2.0             # reject a trade whose stop is more than this many ATR away
RETEST_TOL_ATR = 0.15          # a candle within this distance of the level counts as a retest
INSIDE_CLOSE_ATR = 0.25        # closing this far back inside the level cancels the setup
RETEST_MAX_CANDLES = 12        # the retest must come within 1 hour of the breakout
CONFIRM_MAX_CANDLES = 3        # the confirmation candle must come within 15 minutes of the retest
ENTRY_VALID_CANDLES = 3        # "enter above the candle's high" orders stay valid for 15 minutes
MIN_REWARD_COST_MULT = 4.0     # skip if the 3R reward is less than 4x the trading costs

ORB_MINUTES = 15               # opening range = first 15 minutes of the session
ORB_MAX_BREAKOUT_ATR = 1.0     # skip a breakout that has already run more than 1 ATR past the range

VWAP_ADX_MIN = 20              # ADX(14) must be above this and rising (test 25 separately, don't tune to fit)
VWAP_MAX_ENTRIES = 2           # at most two VWAP-5M entries per session
VWAP_STOP_BUFFER_ATR = 0.25    # ATR buffer beyond the pullback swing
VWAP_SWING_LOOKBACK = 12       # "latest meaningful swing" = the last hour of candles
VWAP_TREND_LOOKBACK = 6        # the trend leg (ADX rising) must be within this many candles before the pullback
SR_BLOCK_R = 2.0               # skip if the previous session's high/low sits within 2R of entry (blocks 3R)

PDH_NEXT_LEVEL_R = 2.0         # skip if the next major level (5-session high/low) is within 2R of entry

# ---------------- RSI signal (same rule for every instrument) ----------------
RSI_PERIOD = 14
TIMEFRAME = "5m"          # 5-minute candles

# How the RSI signal is read:
#   "reversal" -> Buy CALL when RSI crosses back ABOVE 30, Buy PUT when it crosses back BELOW 70
#   "momentum" -> Buy CALL when RSI crosses ABOVE 60,      Buy PUT when it crosses BELOW 40
STRATEGY_MODE = "reversal"
REVERSAL_LEVELS = {"call": 30, "put": 70}
MOMENTUM_LEVELS = {"call": 60, "put": 40}

# ---------------- Option selection ----------------
ITM_STRIKES = 1           # normal days: 1 strike in-the-money
ATM_ON_EXPIRY_DAY = True  # on an index's expiry day use the ATM strike instead

# Backtest premium model: how much the option moves per 1 point of the underlying.
DELTA_ITM = 0.60
DELTA_ATM_EXPIRY = 0.50

# ---------------- Risk limits (apply to EACH instrument and EACH strategy separately) ----------------
MAX_TRADES_PER_DAY = None   # None = unlimited signals; or a number, e.g. 10
DAILY_MAX_LOSS_RS = None    # backtest only: stop for the day after this loss; None = no limit

# Stop-loss / target can be a fixed number of PREMIUM points, or "auto".
# "auto" sizes them from recent volatility (ATR of the last 14 five-minute candles):
#   stop-loss = delta x AUTO_SL_ATR x ATR,  target = stop-loss x AUTO_TARGET_MULT
AUTO_SL_ATR = 1.5
AUTO_TARGET_MULT = 2.0

# NSE trading holidays as "YYYY-MM-DD". If an expiry day is a holiday, expiry moves earlier.
NSE_HOLIDAYS = [
    "2026-11-10",   # Diwali Balipratipada (Tuesday)
    "2026-11-24",   # Guru Nanak Jayanti (Tuesday)
    "2026-12-25",   # Christmas (Friday)
]

# ---------------- Estimated option price (indices only) ----------------
# The bot has no live option prices, so for Nifty, Sensex and Bank Nifty it estimates the premium
# with the Black-Scholes formula from the index level, days to expiry and India VIX, and turns your
# stop-loss/target points into rupee prices. Always confirm the real price in Sahi.
ESTIMATE_PREMIUM = True
RISK_FREE_RATE = 0.065        # yearly, roughly the Indian T-bill rate
INDIA_VIX_FALLBACK = 13.0     # used if India VIX can't be downloaded
# Bank Nifty swings more than Nifty, so its volatility is India VIX x this factor.
VIX_MULTIPLIER = {"NIFTY": 1.0, "SENSEX": 1.0, "BANKNIFTY": 1.25}

# Used only for commodities: converts international prices (US$) to MCX rupee prices.
# The live USD/INR rate is downloaded each run; this is the fallback if that fails.
USDINR_FALLBACK = 88.0

# ---------------- Instruments ----------------
# enabled         True / False to switch an instrument on or off
# units_per_lot   rupees gained per 1 point of premium per lot (the lot size for indices;
#                 for MCX: GOLDM 100 g quoted per 10 g = 10, SILVERM 5 kg quoted per kg = 5, ...)
# lots            how many lots each alert suggests
# strike_step     gap between strikes (indices only; for MCX you pick the strike in Sahi's chain)
# expiry          "weekly" or "monthly" (last <expiry_weekday> of the month); MCX: "chain"
# expiry_weekday  0=Mon 1=Tue 2=Wed 3=Thu 4=Fri
# sl_points / target_points   premium points, or "auto"
# Lot sizes as of the January 2026 NSE revision and BSE's current Sensex lot. Re-check if exchanges revise them.
INSTRUMENTS = {
    "NIFTY": dict(
        enabled=True, name="Nifty 50", exchange="NSE", ticker="^NSEI", segment="index",
        units_per_lot=65, lots=3, strike_step=50, expiry="weekly", expiry_weekday=1,
        sl_points=20, target_points=40, cost_rs=80,
        session=("09:15", "15:30"), entry=("09:30", "14:45"), square_off="15:15",
    ),
    "SENSEX": dict(
        enabled=True, name="BSE Sensex", exchange="BSE", ticker="^BSESN", segment="index",
        units_per_lot=20, lots=1, strike_step=100, expiry="weekly", expiry_weekday=3,
        sl_points="auto", target_points="auto", cost_rs=80,
        session=("09:15", "15:30"), entry=("09:30", "14:45"), square_off="15:15",
    ),
    "BANKNIFTY": dict(
        enabled=True, name="Bank Nifty", exchange="NSE", ticker="^NSEBANK", segment="index",
        units_per_lot=30, lots=1, strike_step=100, expiry="monthly", expiry_weekday=1,
        sl_points="auto", target_points="auto", cost_rs=80,
        session=("09:15", "15:30"), entry=("09:30", "14:45"), square_off="15:15",
    ),
    # ---- MCX commodities (options on Mini gold/silver, standard crude and natural gas) ----
    # Signals use international prices (COMEX/NYMEX), which move almost exactly with MCX.
    "GOLDM": dict(
        enabled=True, name="Gold Mini", exchange="MCX", ticker="GC=F", segment="commodity",
        convert="usd_oz_to_inr_10g", quote="₹ per 10 g",
        units_per_lot=10, lots=1, expiry="chain",
        sl_points="auto", target_points="auto", cost_rs=100,
        session=("09:00", "23:30"), entry=("09:15", "23:00"), square_off="23:15",
    ),
    "SILVERM": dict(
        enabled=True, name="Silver Mini", exchange="MCX", ticker="SI=F", segment="commodity",
        convert="usd_oz_to_inr_kg", quote="₹ per kg",
        units_per_lot=5, lots=1, expiry="chain",
        sl_points="auto", target_points="auto", cost_rs=100,
        session=("09:00", "23:30"), entry=("09:15", "23:00"), square_off="23:15",
    ),
    "CRUDEOIL": dict(
        enabled=True, name="Crude Oil", exchange="MCX", ticker="CL=F", segment="commodity",
        convert="usd_to_inr", quote="₹ per barrel",
        units_per_lot=100, lots=1, expiry="chain",
        sl_points="auto", target_points="auto", cost_rs=100,
        session=("09:00", "23:30"), entry=("09:15", "23:00"), square_off="23:15",
    ),
    "NATURALGAS": dict(
        enabled=True, name="Natural Gas", exchange="MCX", ticker="NG=F", segment="commodity",
        convert="usd_to_inr", quote="₹ per mmBtu",
        units_per_lot=1250, lots=1, expiry="chain",
        sl_points="auto", target_points="auto", cost_rs=100,
        session=("09:00", "23:30"), entry=("09:15", "23:00"), square_off="23:15",
    ),
}


def enabled_instruments():
    return {k: v for k, v in INSTRUMENTS.items() if v.get("enabled", True)}


# ---------------- Alerts ----------------
# Telegram details are SECRET, so they are never written in this file.
#   - On your computer: put them in a file called secrets.env (copy secrets.env.example).
#   - On GitHub: add them under Settings > Secrets and variables > Actions.
# Without them you still get on-screen alerts with a beep. See README.md.
import os as _os
from pathlib import Path as _Path


def _load_secrets():
    here = _Path(__file__).resolve().parent
    for name in ("secrets.env", ".env"):
        f = here / name
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            _os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_secrets()
TELEGRAM_BOT_TOKEN = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _os.environ.get("TELEGRAM_CHAT_ID", "")
