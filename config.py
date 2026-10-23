"""
Settings for the Nifty RSI-14 options strategy.
Change the numbers here; you don't need to touch the other files.
"""

# ---------------- RSI signal ----------------
RSI_PERIOD = 14
TIMEFRAME = "5m"          # 5-minute candles on the Nifty 50 index

# How the RSI signal is read:
#   "reversal" -> Buy CALL when RSI crosses back ABOVE 30 (bounce from oversold)
#                 Buy PUT  when RSI crosses back BELOW 70 (fall from overbought)
#   "momentum" -> Buy CALL when RSI crosses ABOVE 60, Buy PUT when it crosses BELOW 40
STRATEGY_MODE = "reversal"

REVERSAL_LEVELS = {"call": 30, "put": 70}
MOMENTUM_LEVELS = {"call": 60, "put": 40}

# ---------------- Option selection ----------------
STRIKE_STEP = 50          # Nifty strikes are 50 points apart
ITM_STRIKES = 1           # normal days: 1 strike in-the-money (CE = ATM-50, PE = ATM+50)
ATM_ON_EXPIRY_DAY = True  # on expiry day use the ATM strike instead

EXPIRY_WEEKDAY = 1        # 0=Mon, 1=Tue ... Nifty weekly expiry is currently Tuesday
# If the expiry Tuesday is an NSE holiday, expiry moves to the previous trading day.
# Add NSE trading holidays here as "YYYY-MM-DD" so expiry dates come out right.
NSE_HOLIDAYS = [
    # "2026-11-10",
]

# ---------------- Position size ----------------
LOT_SIZE = 65             # Nifty lot size (NSE, from Jan 2026 series). Re-check if NSE revises it.
LOTS = 3                  # you said 3-5 lots

# ---------------- Exits (in OPTION PREMIUM points) ----------------
STOP_LOSS_POINTS = 20     # exit if the option premium falls 20 points below your buy price
TARGET_POINTS = 40        # exit if the option premium rises 40 points above your buy price

# ---------------- Timing (IST) ----------------
FIRST_ENTRY_TIME = "09:30"    # skip the first 15 minutes (noisy open)
LAST_ENTRY_TIME = "14:45"     # no new trades after this
SQUARE_OFF_TIME = "15:15"     # close everything by this time
MAX_TRADES_PER_DAY = 3        # stop taking new signals after this many trades in a day
DAILY_MAX_LOSS_RS = 10000     # backtest stops trading for the day after losing this much

# ---------------- Backtest premium model ----------------
# Free sources don't have historical 5-minute OPTION prices, so the backtest
# estimates premium moves from Nifty moves using delta (how much the option
# moves per 1 point of Nifty). Typical values:
DELTA_ITM = 0.60          # 1-strike ITM option on a normal day
DELTA_ATM_EXPIRY = 0.50   # ATM option on expiry day

# Rough cost per round trip (buy + sell) for the whole position:
# Sahi brokerage Rs 10 x 2 orders + STT, exchange charges, GST, stamp duty.
# Check Sahi's brokerage calculator for your exact numbers.
COST_PER_TRADE_RS = 80

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
