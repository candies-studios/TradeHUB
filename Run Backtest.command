#!/bin/bash
# Double-click to run the backtest. The dashboard opens in your browser when it finishes.
cd "$(dirname "$0")" || exit 1
echo "Installing what the program needs (only slow the first time)..."
python3 -m pip install --quiet --user -r requirements.txt
echo "Running the backtest..."
python3 backtest.py --html report.html && open report.html
echo
echo "Done. You can close this window."
