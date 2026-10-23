# RSI-14 Options — Backtest Dashboard + Alerts

A research tool for one strategy: buy options when RSI-14 on 5-minute candles crosses your levels. It **does not place orders**; you place trades yourself on Sahi.

| Instrument | Exchange | Lot | Expiry | Alerts between (IST) |
|---|---|---|---|---|
| Nifty 50 | NSE | 65 | weekly, Tuesday | 09:30–14:45 |
| BSE Sensex | BSE | 20 | weekly, Thursday | 09:30–14:45 |
| Bank Nifty | NSE | 30 | monthly, last Tuesday | 09:30–14:45 |
| Gold Mini (GOLDM) | MCX | 100 g | nearest, pick in Sahi | 09:15–23:00 |
| Silver Mini (SILVERM) | MCX | 5 kg | nearest, pick in Sahi | 09:15–23:00 |
| Crude Oil | MCX | 100 bbl | nearest, pick in Sahi | 09:15–23:00 |
| Natural Gas | MCX | 1,250 mmBtu | nearest, pick in Sahi | 09:15–23:00 |

- **Index alerts** give the exact strike and expiry. **MCX alerts** tell you the side (CE/PE) and to take the 1-strike in-the-money option at the nearest expiry from Sahi's option chain.
- **Stop-loss and target:** Nifty uses your fixed 20 / 40 premium points. The others use `"auto"`, sized from recent volatility, and the alert states the exact numbers.
- **Settings:** lots, on/off switches and stop-loss values for each instrument are in `config.py` under `INSTRUMENTS`. Set `enabled=False` to stop an instrument.
- **Commodity data:** the free data feed has no MCX prices, so gold, silver, crude and natural gas signals come from their international prices (COMEX/NYMEX), converted to rupees. MCX follows these closely, but not tick for tick.

There are two ways to use it, and **neither needs the Terminal**.

---

## Option A — Run everything on GitHub (nothing to install)

GitHub runs the programs on its own computers:
- **Backtest dashboard**: a web page at `https://YOUR-USERNAME.github.io/YOUR-REPO/` showing win rate, P&L, a chart and every trade. It refreshes each weekday at 16:00 IST, or whenever you press a button.
- **RSI alerts**: checks every 5 minutes during market hours and sends you a Telegram message when your rule fires.

### 1. Create the repository
On github.com click **+ → New repository**. Give it a name (for example `nifty-rsi-alerts`) and choose **Public**. Free GitHub accounts can only publish a web page from a public repository. This is safe, because no secrets are stored in these files. Click **Create repository**.

### 2. Upload the files
On the repository page, click **Add file → Upload files**. Drag in all the visible files, including the `github-setup` folder, and click **Commit changes**.

> Never upload a file called `secrets.env`.

### 3. Create the two automations (copy and paste)
GitHub only runs automations stored in a folder called `.github/workflows`. Mac hides that folder, so create the files directly on github.com instead:

1. Click **Add file → Create new file**.
2. In the name box, type exactly `.github/workflows/dashboard.yml`. Each `/` you type creates a folder.
3. On your Mac, open `github-setup/dashboard.yml` with TextEdit. Select all, copy, and paste it into the big box on GitHub.
4. Click **Commit changes**.
5. Repeat for `.github/workflows/alerts.yml` using `github-setup/alerts.yml`.

### 4. Add your Telegram details as secrets
Go to **Settings → Secrets and variables → Actions → New repository secret** and add two secrets:
- Name `TELEGRAM_BOT_TOKEN`, with your bot token as the value.
- Name `TELEGRAM_CHAT_ID`, with your chat ID as the value.

GitHub keeps these hidden. They never appear in your files. (How to get them is under *Telegram setup* below.)

### 5. Check the website
Saving `dashboard.yml` starts the first backtest automatically. Open the **Actions** tab and wait for the green tick (about 2 minutes). The automation saves an `index.html` into the repository, and your website then shows the dashboard instead of this README. Allow a minute or two for GitHub Pages to refresh.

- **Website address:** `https://YOUR-USERNAME.github.io/YOUR-REPO/`
- **Pages setting:** this uses the normal **Settings → Pages → Deploy from a branch → main / (root)** setting, which new repositories already have.
- **Run it again any time:** go to **Actions → Backtest dashboard → Run workflow** and choose reversal or momentum.
- **If the run fails with a permission error:** go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, click **Save**, and run it again.

### 6. Alerts
**RSI alerts** starts on its own every weekday from 09:00 to 23:30 IST: indices during NSE/BSE hours, commodities during MCX hours. To pause it, go to **Actions → RSI alerts → ⋯ → Disable workflow**. To test it immediately, click **Run workflow**.

**Know the limits of GitHub alerts**
- GitHub starts scheduled runs when it has capacity. They are often a few minutes late and occasionally skipped. Treat these alerts as a heads-up, not precise timing. For on-time alerts, use Option B.
- Free usage: unlimited for public repositories. A private repository gets 2,000 minutes a month, and the alerts use roughly 1,600 of them.
- Market data comes from Yahoo Finance, which can occasionally refuse requests from GitHub's servers. A failed check simply tries again 5 minutes later.

### 7. Paper log
Your website has a second page, **Paper log** (`…/paper.html`, or click **Paper log** at the top of the dashboard). Each alert the bot sends is saved to `alerts_log.csv` and appears there automatically. Type the option price you saw in Sahi when the alert came (entry), and where it would have closed (exit). The page tracks your win rate and net P&L. Entries are saved in the browser you use, so download a backup now and then.

### Changing settings on GitHub
Click `config.py` in the repository, click the **pencil icon**, change a number (for example `LOTS = 4`), and click **Commit changes**. The next run uses the new value.

---

## Option B — Run it on your Mac by double-clicking

1. Install Python from **python.org → Downloads → macOS** (a normal installer). One time only.
2. Double-click **Run Backtest.command**. A window shows progress, and the dashboard opens in your browser when it's done.
   - The first time, macOS may say it can't be opened. If so, **right-click the file → Open → Open**. After that, double-clicking works.
3. On a trading day before 9:30, double-click **Start Alerts.command** and leave its window open. Alerts appear there with a beep, and on Telegram if set up. Close the window to stop.

**Telegram on your Mac:** right-click `secrets.env.example` → **Duplicate**. Rename the copy to `secrets.env`; if macOS asks, choose **Use .env**. Open it with TextEdit, paste your two values after the `=` signs, and save. This file stays on your Mac and must never be uploaded.

---

## Telegram setup (free)
1. In Telegram, message **@BotFather**, send `/newbot` and follow the steps. Copy the **token** it gives you.
2. Send any message to your new bot.
3. In a browser, open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`. The number after `"chat":{"id":` is your chat ID.

## What's in this folder
| File | What it does |
|---|---|
| `config.py` | All strategy settings |
| `strategy.py` | RSI, signals, strikes, expiries and stop-loss sizing |
| `data.py` | Downloads market data and converts commodity prices to rupees |
| `backtest.py` | Tests the strategy on past data |
| `report.py` | Builds the dashboard web page |
| `paper.html` | Paper log page for recording alerts with real Sahi prices |
| `live_alerts.py` | Watches the market and alerts you |
| `requirements.txt` | Python packages the programs need |
| `secrets.env.example` | Template for your Telegram details |
| `.gitignore` | Stops secrets and generated files being committed with git |
| `.github/workflows/` | The two GitHub automations (dashboard and alerts) |
| `github-setup/` | Visible copies of the two automations, to copy and paste on github.com |
| `*.command` | Double-click launchers for Mac |

## Things to know
- **The backtest is optimistic.** Free data has no historical option prices, so premiums are estimated from Nifty's move (delta 0.6 ITM, 0.5 ATM on expiry). Time decay is ignored. A losing backtest is a clear "no".
- **Check the RSI value against Sahi's 5-minute RSI-14** for the first few days. Yahoo data can lag slightly.
- **Holidays:** add NSE holidays to `NSE_HOLIDAYS` in `config.py` so the expiry dates shown are right. Update `LOT_SIZE` if NSE changes it.
- **Risk:** at 3 lots, a stopped-out trade loses about ₹4,000. Paper-trade the alerts for a few weeks before using real money. This is a research tool, not financial advice.
