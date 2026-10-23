# Nifty RSI-14 Options — Backtest Dashboard + Alerts

A research tool for one strategy: buy Nifty options when RSI-14 on 5-minute Nifty candles crosses your levels. It **does not place orders**. You place trades yourself on Sahi.

| Setting | Value (change in `config.py`) |
|---|---|
| Chart | Nifty 50 index, 5-minute candles, RSI-14 |
| Action | Buy CALL on a bullish signal, buy PUT on a bearish one |
| Strike | 1 strike ITM; ATM on expiry day (Tuesday) |
| Size | 3 lots × 65 |
| Exit | Fixed stop-loss / target in premium points, or 15:15 |

There are two ways to use it, and **neither needs the Terminal**.

---

## Option A — Run everything on GitHub (nothing to install)

GitHub runs the programs on its own computers:
- **Backtest dashboard**: a web page at `https://YOUR-USERNAME.github.io/YOUR-REPO/` showing win rate, P&L, a chart and every trade. It refreshes each weekday at 16:00 IST, or whenever you press a button.
- **RSI alerts**: checks every 5 minutes during market hours and sends you a Telegram message when your rule fires.

### 1. Create the repository
On github.com click **+ → New repository**. Give it a name (for example `nifty-rsi-alerts`) and choose **Public**. Free GitHub accounts can only publish a web page from a public repository. This is safe, because no secrets are stored in these files. Click **Create repository**.

### 2. Upload the files
1. Unzip the folder on your Mac.
2. Open it in Finder and press **Cmd + Shift + .** (full stop). This shows the hidden `.github` folder and `.gitignore` file. They must be uploaded too.
3. On the new repository page, click **uploading an existing file**.
4. Select **everything inside the folder**, including `.github`, and drag it in. Click **Commit changes**.
5. Check that you can see a `.github` folder in the repository's file list.

> Never upload a file called `secrets.env`. The `.gitignore` file only protects you when you use git; the web uploader will upload whatever you drag in.

### 3. Add your Telegram details as secrets
Go to **Settings → Secrets and variables → Actions → New repository secret** and add two secrets:
- Name `TELEGRAM_BOT_TOKEN`, with your bot token as the value.
- Name `TELEGRAM_CHAT_ID`, with your chat ID as the value.

GitHub keeps these hidden. They never appear in your files, and nobody viewing the repository can see them. (How to get them is under *Telegram setup* below.)

### 4. Turn on the website
Go to **Settings → Pages**. Under **Build and deployment → Source**, choose **GitHub Actions**.

### 5. Run the backtest
Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**. Then:
1. Click **Backtest dashboard** on the left.
2. Click **Run workflow**, choose **reversal** or **momentum**, and click **Run workflow** again.
3. After about 2 minutes, a green tick appears. Your dashboard is at `https://YOUR-USERNAME.github.io/YOUR-REPO/`.

### 6. Alerts
**RSI alerts** starts on its own every weekday from 09:15 to 15:30 IST. To pause it, go to **Actions → RSI alerts → ⋯ → Disable workflow**. To test it immediately, click **Run workflow**.

**Know the limits of GitHub alerts**
- GitHub starts scheduled runs when it has capacity. They are often a few minutes late and occasionally skipped. Treat these alerts as a heads-up, not precise timing. For on-time alerts, use Option B.
- Free usage: unlimited for public repositories. A private repository gets 2,000 minutes a month, and the alerts use roughly 1,600 of them.
- Market data comes from Yahoo Finance, which can occasionally refuse requests from GitHub's servers. A failed check simply tries again 5 minutes later.

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
| `strategy.py` | RSI, signals, strike and expiry logic |
| `backtest.py` | Tests the strategy on past data |
| `report.py` | Builds the dashboard web page |
| `live_alerts.py` | Watches the market and alerts you |
| `requirements.txt` | Python packages the programs need |
| `secrets.env.example` | Template for your Telegram details |
| `.gitignore` | Stops secrets and generated files being committed with git |
| `.github/workflows/` | The two GitHub automations (dashboard and alerts) |
| `*.command` | Double-click launchers for Mac |

## Things to know
- **The backtest is optimistic.** Free data has no historical option prices, so premiums are estimated from Nifty's move (delta 0.6 ITM, 0.5 ATM on expiry). Time decay is ignored. A losing backtest is a clear "no".
- **Check the RSI value against Sahi's 5-minute RSI-14** for the first few days. Yahoo data can lag slightly.
- **Holidays:** add NSE holidays to `NSE_HOLIDAYS` in `config.py` so the expiry dates shown are right. Update `LOT_SIZE` if NSE changes it.
- **Risk:** at 3 lots, a stopped-out trade loses about ₹4,000. Paper-trade the alerts for a few weeks before using real money. This is a research tool, not financial advice.
