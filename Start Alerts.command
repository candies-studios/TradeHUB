#!/bin/bash
# Double-click before 9:30 on a trading day. Keep this window open; close it to stop.
cd "$(dirname "$0")" || exit 1
echo "Installing what the program needs (only slow the first time)..."
python3 -m pip install --quiet --user -r requirements.txt
python3 live_alerts.py
