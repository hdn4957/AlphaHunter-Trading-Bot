# AlphaHunter

Technical-analysis momentum trading bot in Python. Built for a Financial Management course.
Paper trading only.

## Features
- Interactive Brokers (IBAPI) for execution, Alpaca for market data
- Pandas-based indicators: RSI, MACD, ATR, VWAP, Bollinger Bands
- ATR position sizing, kill switch, connection watchdog
- SQLite position persistence
- Tkinter GUI and Flask dashboard

## Setup
1. Install dependencies: pip install -r requirements.txt
2. Copy .env.example to .env and fill in your keys
3. Run: python ALPHAHUNTER.py

## Disclaimer
Educational project. Not financial advice.
