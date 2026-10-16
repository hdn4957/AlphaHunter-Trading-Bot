import threading
import time
import asyncio
import os
import csv
import sqlite3
import json
import smtplib
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from email.mime.text import MIMEText
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.live import StockDataStream
from alpaca.data.models import Quote
from alpaca.trading.client import TradingClient
import tkinter as tk
from tkinter import ttk, scrolledtext
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order

try:
    from flask import Flask, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

try:
    from alpaca.data.requests import NewsRequest
    NEWS_AVAILABLE = True
except ImportError:
    NEWS_AVAILABLE = False

# =============================================================================
# CONFIG
# =============================================================================
load_dotenv()
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
FLASK_PORT        = int(os.getenv("FLASK_PORT", 5000))

ET = ZoneInfo("America/New_York")

# Economic calendar — update monthly. Format: (date, hour_ET, min_ET, name, blackout_min)
ECONOMIC_EVENTS = [
    ("2026-03-20", 14,  0, "FOMC Decision",  30),
    ("2026-04-03",  8, 30, "NFP Report",     30),
    ("2026-04-10",  8, 30, "CPI Report",     20),
    ("2026-04-30", 14,  0, "FOMC Decision",  30),
    ("2026-05-02",  8, 30, "NFP Report",     30),
    ("2026-05-13",  8, 30, "CPI Report",     20),
    ("2026-06-11", 14,  0, "FOMC Decision",  30),
    ("2026-06-06",  8, 30, "NFP Report",     30),
]

# Minimal web dashboard HTML (auto-refreshes every 5 s)
_DASHBOARD_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>AlphaHunter Dashboard</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0a0a0a;color:#ccc;font-family:Consolas,monospace;padding:20px}
  h1{color:#00ffaa;margin-bottom:16px}h2{color:#666;margin:20px 0 8px}
  .grid{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px}
  .card{background:#1a1a1a;padding:14px 18px;border-radius:6px;min-width:160px}
  .card h3{color:#666;font-size:10px;margin-bottom:6px}
  .big{font-size:22px;font-weight:bold}
  .g{color:#00ff00}.r{color:#ff3333}.y{color:#ffdd44}.c{color:#00ffaa}
  table{width:100%;border-collapse:collapse}
  th{color:#555;text-align:left;padding:6px 10px;border-bottom:1px solid #222;font-size:10px}
  td{padding:6px 10px;border-bottom:1px solid #111;font-size:11px}
  .footer{color:#333;font-size:10px;margin-top:20px}
</style></head><body>
<h1>&#9660; ALPHA HUNTER v5.0</h1>
<div id="root">Connecting...</div>
<script>
async function refresh(){
  try{
    const d=await(await fetch('/api/status')).json();
    const pc=v=>v>=0?'g':'r', fmt=v=>'$'+v.toFixed(2);
    let cards=`
      <div class="card"><h3>TOTAL P&L</h3><div class="big ${pc(d.total_pnl)}">${fmt(d.total_pnl)}</div></div>
      <div class="card"><h3>DAILY P&L</h3><div class="big ${pc(d.daily_pnl)}">${fmt(d.daily_pnl)}</div></div>
      <div class="card"><h3>WIN RATE</h3><div class="big c">${(d.metrics.win_rate||0).toFixed(1)}%</div></div>
      <div class="card"><h3>TRADES</h3><div class="big">${d.metrics.trades}</div></div>
      <div class="card"><h3>SHARPE</h3><div class="big">${(d.metrics.sharpe||0).toFixed(2)}</div></div>
      <div class="card"><h3>SORTINO</h3><div class="big">${(d.metrics.sortino||0).toFixed(2)}</div></div>
      <div class="card"><h3>MAX DD</h3><div class="big r">${fmt(-(d.metrics.max_drawdown||0))}</div></div>
      <div class="card"><h3>VIX PROXY</h3><div class="big y">${(d.vix_proxy||0).toFixed(1)}%</div></div>
      <div class="card"><h3>STATUS</h3>
        <div>IBKR <b class="${d.ib_connected?'g':'r'}">${d.ib_connected?'LIVE':'DOWN'}</b></div>
        <div>ALPACA <b class="${d.alpaca_connected?'g':'r'}">${d.alpaca_connected?'LIVE':'DOWN'}</b></div>
        <div>MARKET <b class="${d.market_open?'g':'r'}">${d.market_open?'OPEN':'CLOSED'}</b></div>
        <div>ALGO <b class="${d.trading_halted?'r':'g'}">${d.trading_halted?'HALTED':'RUNNING'}</b></div>
      </div>`;
    let posRows=Object.entries(d.positions||{}).map(([s,p])=>`<tr>
      <td>${s}</td><td class="${p.side==='LONG'?'g':'r'}">${p.side}</td>
      <td>${fmt(p.entry)}</td><td>${fmt(p.current)}</td><td>${p.qty}</td>
      <td class="${pc(p.unrealized_pnl)}">${fmt(p.unrealized_pnl)}</td>
      <td class="g">${fmt(p.target)}</td><td class="r">${fmt(p.stop)}</td>
      <td class="y">${p.hold_min.toFixed(1)}m</td></tr>`).join('')||
      '<tr><td colspan="9" style="color:#444">No open positions</td></tr>';
    let sigRows=Object.entries(d.signals||{}).map(([s,g])=>`<tr>
      <td>${s}</td><td class="${g.signal==='BUY'?'g':g.signal==='SELL'?'r':''}">${g.signal||'--'}</td>
      <td>${(g.price||0).toFixed(2)}</td><td>${(g.rsi||0).toFixed(1)}</td>
      <td>${g.macd_bullish?'&#8593;':'&#8595;'}</td><td>${(g.score||0).toFixed(2)}</td></tr>`).join('')||
      '<tr><td colspan="6" style="color:#444">No data</td></tr>';
    document.getElementById('root').innerHTML=`
      <div class="grid">${cards}</div>
      <h2>OPEN POSITIONS (${Object.keys(d.positions||{}).length})</h2>
      <table><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Current</th><th>Qty</th>
        <th>Unrealized</th><th>Target</th><th>Stop</th><th>Hold</th></tr>${posRows}</table>
      <h2>SIGNAL WATCHLIST</h2>
      <table><tr><th>Symbol</th><th>Signal</th><th>Price</th><th>RSI</th><th>MACD</th><th>Score</th></tr>
        ${sigRows}</table>
      <p class="footer">Auto-refresh 5s &middot; AlphaHunter v5.0 &middot; <a href="/api/status" style="color:#444">raw JSON</a></p>`;
  }catch(e){document.getElementById('root').innerHTML='<p style="color:red">Server unreachable</p>';}
}
refresh();setInterval(refresh,5000);
</script></body></html>"""


# =============================================================================
# HELPERS
# =============================================================================
def is_market_open():
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    c = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return o <= now < c

def is_premarket():
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=9,  minute=0,  second=0, microsecond=0)
    end   = now.replace(hour=9,  minute=25, second=0, microsecond=0)
    return start <= now < end

def near_economic_event():
    now       = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")
    for date_str, hour, minute, name, blackout in ECONOMIC_EVENTS:
        if date_str == today_str:
            event_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if abs((now - event_time).total_seconds() / 60) <= blackout:
                return True, name
    return False, ""


# =============================================================================
# BACKTEST ENGINE
# =============================================================================
class BacktestEngine:
    """Replay historical 1-min bars through the strategy logic and report metrics."""

    def __init__(self, historical_client, symbols, params):
        self.client  = historical_client
        self.symbols = symbols
        self.params  = params

    def run(self, days_back=5):
        all_trades = []
        for sym in self.symbols:
            try:
                all_trades.extend(self._backtest_symbol(sym, days_back))
            except Exception:
                pass

        pnl_list  = [t['pnl'] for t in all_trades]
        wins      = [p for p in pnl_list if p > 0]
        losses    = [p for p in pnl_list if p <= 0]
        cum_pnl   = list(np.cumsum(pnl_list)) if pnl_list else []

        return {
            'total_trades': len(all_trades),
            'total_pnl':    sum(pnl_list),
            'win_rate':     len(wins) / len(all_trades) * 100 if all_trades else 0,
            'avg_win':      float(np.mean(wins))   if wins   else 0,
            'avg_loss':     float(np.mean(losses)) if losses else 0,
            'sharpe':       self._sharpe(pnl_list),
            'max_drawdown': self._max_drawdown(cum_pnl),
            'trades':       all_trades,
            'equity_curve': cum_pnl,
        }

    def _backtest_symbol(self, sym, days_back):
        end   = datetime.now(ET)
        start = end - timedelta(days=days_back + 3)

        req  = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start, end=end, limit=3000)
        bars = self.client.get_stock_bars(req).data.get(sym, [])
        if len(bars) < 30:
            return []

        df = pd.DataFrame([{
            'Time': b.timestamp, 'Close': b.close,
            'High': b.high, 'Low': b.low, 'Volume': b.volume
        } for b in bars])
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)

        df['SMA20']    = df['Close'].rolling(20).mean()
        delta          = df['Close'].diff()
        gain           = delta.where(delta > 0,  0).rolling(14).mean()
        loss           = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['RSI']      = 100 - (100 / (1 + gain / loss))
        ema12          = df['Close'].ewm(span=12, adjust=False).mean()
        ema26          = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD']     = ema12 - ema26
        df['MACD_Sig'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['AvgVol20'] = df['Volume'].rolling(20).mean()

        p = self.params
        tp_f    = p.get('tp_pct',        2.0)  / 100
        sl_f    = p.get('sl_pct',        1.0)  / 100
        trail_f = p.get('trail_pct',     0.5)  / 100
        rsi_lo  = p.get('rsi_min',      50.0)
        rsi_hi  = p.get('rsi_max',      70.0)
        vol_th  = p.get('vol_threshold', 1.1)
        hold_s  = p.get('hold_minutes',  15)   * 60
        slip_f  = p.get('slippage_pct',  0.0)  / 100   # per-side slippage
        qty     = 100

        trades, in_trade = [], False
        entry_price = highest = trailing_stop = 0
        entry_time = None

        for i in range(26, len(df)):
            row = df.iloc[i]
            if pd.isna(row['SMA20']) or pd.isna(row['RSI']):
                continue

            if not in_trade:
                vol_r  = row['Volume'] / row['AvgVol20'] if row['AvgVol20'] > 0 else 1
                dev    = (row['Close'] - row['SMA20']) / row['SMA20'] * 100
                macd_b = row['MACD'] > row['MACD_Sig']
                if (row['Close'] > row['SMA20'] and dev > 0.2
                        and rsi_lo < row['RSI'] < rsi_hi
                        and vol_r > vol_th and macd_b):
                    in_trade      = True
                    # Apply entry slippage: pay slightly more on the buy
                    entry_price   = row['Close'] * (1 + slip_f)
                    entry_time    = df.index[i]
                    highest       = entry_price
                    trailing_stop = entry_price * (1 - sl_f)
            else:
                if row['Close'] > highest:
                    highest       = row['Close']
                    new_t         = highest * (1 - trail_f)
                    if new_t > trailing_stop:
                        trailing_stop = new_t

                hold_s_elapsed = (df.index[i] - entry_time).total_seconds()
                reason = None
                if row['Close'] >= entry_price * (1 + tp_f):   reason = 'TP'
                elif row['Close'] <= trailing_stop:             reason = 'TRAIL'
                elif hold_s_elapsed > hold_s:                   reason = 'TIME'

                if reason:
                    # Apply exit slippage: receive slightly less on the sell
                    exit_price = float(row['Close']) * (1 - slip_f)
                    trades.append({
                        'symbol':      sym,
                        'entry_time':  entry_time,
                        'exit_time':   df.index[i],
                        'entry_price': entry_price,
                        'exit_price':  exit_price,
                        'qty':         qty,
                        'pnl':         (exit_price - entry_price) * qty,
                        'exit_reason': reason,
                        'hold_min':    hold_s_elapsed / 60,
                    })
                    in_trade = False

        return trades

    @staticmethod
    def _sharpe(pnl_list):
        if len(pnl_list) < 3:
            return 0.0
        r = np.array(pnl_list, dtype=float)
        s = np.std(r)
        return float((np.mean(r) / s) * np.sqrt(252 * 20)) if s > 0 else 0.0

    @staticmethod
    def _max_drawdown(cum_pnl):
        if not cum_pnl:
            return 0.0
        c    = np.array(cum_pnl)
        peak = np.maximum.accumulate(c)
        return float(np.max(peak - c))


# =============================================================================
# FLASK WEB DASHBOARD
# =============================================================================
class FlaskDashboard:
    def __init__(self, gui):
        self.gui = gui
        if not FLASK_AVAILABLE:
            return
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        self.app = Flask(__name__)
        self._register_routes()

    def _register_routes(self):
        gui = self.gui
        app = self.app

        @app.route('/')
        def index():
            return _DASHBOARD_HTML

        @app.route('/api/status')
        def status():
            with gui.positions_lock:
                pos_out = {}
                for sym, pos in gui.positions.items():
                    cur = gui.stock_signals.get(sym, {}).get('price', pos['entry_price'])
                    mult = 1 if pos['side'] == 'LONG' else -1
                    unr  = (cur - pos['entry_price']) * pos['qty'] * mult
                    pos_out[sym] = {
                        'side':           pos['side'],
                        'entry':          pos['entry_price'],
                        'current':        cur,
                        'qty':            pos['qty'],
                        'unrealized_pnl': unr,
                        'target':         pos['target'],
                        'stop':           pos['stop_loss'],
                        'hold_min':       (time.time() - pos['open_time']) / 60,
                    }
            sig_out = {s: {k: v for k, v in d.items() if k != 'df'}
                       for s, d in gui.stock_signals.items()}
            sh, so = gui._calc_ratios()
            return jsonify({
                'total_pnl':       gui.total_pnl,
                'daily_pnl':       gui.daily_pnl,
                'positions':       pos_out,
                'signals':         sig_out,
                'trading_halted':  gui.trading_halted,
                'ib_connected':    gui.ib_connected,
                'alpaca_connected':gui.alpaca_connected,
                'market_open':     is_market_open(),
                'vix_proxy':       gui.vix_proxy,
                'metrics': {
                    'trades':       gui.trade_count,
                    'win_rate':    (gui.win_count / gui.trade_count * 100)
                                    if gui.trade_count > 0 else 0,
                    'sharpe':      sh,
                    'sortino':     so,
                    'max_drawdown': gui.max_drawdown,
                },
            })

    def start(self):
        if not FLASK_AVAILABLE:
            return
        threading.Thread(
            target=lambda: self.app.run(
                host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False),
            daemon=True).start()


# =============================================================================
# IBAPI WRAPPER
# =============================================================================
class TradingApp(EWrapper, EClient):
    def __init__(self, gui):
        EClient.__init__(self, self)
        self.gui           = gui
        self.next_order_id = None
        self.order_map     = {}   # {order_id: {symbol, action, side}}

    def nextValidId(self, orderId):
        self.next_order_id    = orderId
        self.gui.ib_connected = True
        self.gui.root.after(0, self.gui.update_connection_display)
        self.gui.log(f"[SYSTEM] IBKR Connected. Order ID base: {orderId}")

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice,
                    permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        if status != "Filled":
            return
        info   = self.order_map.get(orderId, {})
        symbol = info.get('symbol', self.gui.chart_symbol)
        action = info.get('action', 'UNKNOWN')
        side   = info.get('side',   'LONG')
        qty    = int(filled)

        self.gui.log(
            f"*** ORDER FILLED *** {action} {symbol} @ ${avgFillPrice:.2f} | "
            f"Qty: {qty} | Side: {side}")

        opening = (action == 'BUY'  and side == 'LONG') or \
                  (action == 'SELL' and side == 'SHORT')

        if opening:
            self.gui.root.after(0, self.gui.on_position_opened,
                                symbol, side, avgFillPrice, qty)
        else:
            self.gui.root.after(0, self.gui.on_position_closed,
                                symbol, side, avgFillPrice, qty)

    def connectionClosed(self):
        self.gui.ib_connected = False
        self.gui.root.after(0, self.gui.update_connection_display)
        self.gui.log("[IBKR] Connection closed.")

    def error(self, reqId, errorCode, errorString):
        if errorCode not in [2104, 2106, 2158]:
            self.gui.log(f"[IB ERROR {errorCode}] {errorString}")
        if errorCode in [1100, 1102, 2110]:
            self.gui.ib_connected = False
            self.gui.root.after(0, self.gui.update_connection_display)


# =============================================================================
# MAIN GUI
# =============================================================================
class AlphaHunterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AlphaHunter v5.0 [LIVE TRADING]")
        self.root.geometry("1650x1100")
        self.root.configure(bg="#0a0a0a")

        # --- Multi-position state ---
        self.positions      = {}           # {sym: {side,entry_price,qty,target,stop_loss,
        self.positions_lock = threading.Lock()  #       highest/lowest,open_time,atr}}
        self.max_positions  = 3
        self.allow_shorts   = False
        self.chart_symbol   = "SPY"        # symbol currently shown in chart

        # --- Signals & trends ---
        self.watched_symbols = ["SPY","QQQ","NVDA","TSLA","AMD","META","AAPL","MSFT"]
        self.stock_signals   = {}
        self.stock_trends    = {}
        self.quote_data      = {}
        self.current_price   = 0.0

        # --- Portfolio ---
        self.total_capital        = 1_000_000.0
        self.etf_symbols          = ["SPY","QQQ"]
        self.etf_allocation       = self.total_capital * 0.30
        self.large_cap_allocation = self.total_capital * 0.60
        self.cash_reserved        = self.total_capital * 0.10

        # --- Parameters (live-adjustable) ---
        self.tp_pct          = 2.0
        self.sl_pct          = 1.0
        self.trail_pct       = 0.5
        self.rsi_min         = 50.0
        self.rsi_max         = 70.0
        self.vol_threshold   = 1.1
        self.hold_time_minutes = 15.0

        # --- Risk ---
        self.trading_halted    = False
        self.total_pnl         = 0.0
        self.daily_pnl         = 0.0
        self.daily_loss_limit  = -10_000.0
        self.last_trade_date   = date.today()

        # --- Performance ---
        self.trade_count    = 0
        self.win_count      = 0
        self.loss_count     = 0
        self.gross_wins     = 0.0
        self.gross_losses   = 0.0
        self.peak_pnl       = 0.0
        self.max_drawdown   = 0.0
        self.trade_returns  = []         # list of per-trade return %
        self.pnl_history    = []         # [(datetime, cumulative_pnl)]

        # --- Macro ---
        self.vix_proxy           = 0.0   # realized vol of SPY as VIX proxy
        self.vix_pause_threshold = 30.0  # pause when proxy vol > 30 %
        self._premarket_done     = False

        # --- Connection ---
        self.ib_connected     = False
        self.alpaca_connected = False

        # --- Persistent storage ---
        base = Path(__file__).parent
        log_dir = base / "logs"
        log_dir.mkdir(exist_ok=True)
        self.log_path = log_dir / f"trading_log_{date.today():%Y%m%d}.csv"
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="") as f:
                csv.writer(f).writerow(["timestamp", "message"])

        self.db_path = base / "trades.db"
        self._init_db()

        # =====================================================================
        # GUI LAYOUT
        # =====================================================================

        # --- TOP BAR ---
        top = tk.Frame(root, bg="#111111", pady=10)
        top.pack(fill="x")

        # LEFT: Branding
        left_f = tk.Frame(top, bg="#111111")
        left_f.pack(side="left", padx=20)
        tk.Label(left_f, text="ALPHA HUNTER", bg="#111111", fg="#00ffaa",
                 font=("Impact", 26, "bold")).pack(anchor="w")
        tk.Label(left_f, text="v5.0 · Real-Time Algo Engine", bg="#111111",
                 fg="#444444", font=("Consolas", 8)).pack(anchor="w")
        conn_row = tk.Frame(left_f, bg="#111111")
        conn_row.pack(anchor="w", pady=(3, 0))
        tk.Label(conn_row, text="IBKR", bg="#111111", fg="#444",
                 font=("Consolas", 7)).pack(side="left")
        self.lbl_ib_status = tk.Label(conn_row, text="●", bg="#111111",
                                      fg="#ff3333", font=("Consolas", 9))
        self.lbl_ib_status.pack(side="left", padx=(2, 10))
        tk.Label(conn_row, text="ALPACA", bg="#111111", fg="#444",
                 font=("Consolas", 7)).pack(side="left")
        self.lbl_alpaca_status = tk.Label(conn_row, text="●", bg="#111111",
                                          fg="#ff3333", font=("Consolas", 9))
        self.lbl_alpaca_status.pack(side="left", padx=(2, 10))
        self.lbl_web_status = tk.Label(conn_row, text=f"WEB :{FLASK_PORT}",
                                       bg="#111111", fg="#555", font=("Consolas", 7))
        self.lbl_web_status.pack(side="left")

        # DIVIDER
        tk.Frame(top, bg="#2a2a2a", width=1).pack(side="left", fill="y", padx=14, pady=6)

        # Symbol + Price + Status
        sym_f = tk.Frame(top, bg="#111111")
        sym_f.pack(side="left")
        self.lbl_symbol = tk.Label(sym_f, text="SPY", bg="#111111", fg="#00ffaa",
                                   font=("Consolas", 18, "bold"))
        self.lbl_symbol.pack(anchor="w")
        self.lbl_price = tk.Label(sym_f, text="$0.00", bg="#111111", fg="#ffffff",
                                  font=("Consolas", 15, "bold"))
        self.lbl_price.pack(anchor="w")
        self.lbl_status = tk.Label(sym_f, text="INITIALIZING...", bg="#111111",
                                   fg="#555555", font=("Consolas", 8))
        self.lbl_status.pack(anchor="w")

        # Bid / Ask
        ba_f = tk.Frame(top, bg="#111111")
        ba_f.pack(side="left", padx=16)
        tk.Label(ba_f, text="BID", bg="#111111", fg="#ff6644",
                 font=("Consolas", 8)).pack(anchor="w")
        self.lbl_bid = tk.Label(ba_f, text="$0.00", bg="#111111", fg="#ff9977",
                                font=("Consolas", 11, "bold"))
        self.lbl_bid.pack(anchor="w")
        tk.Label(ba_f, text="ASK", bg="#111111", fg="#44ff66",
                 font=("Consolas", 8)).pack(anchor="w", pady=(4, 0))
        self.lbl_ask = tk.Label(ba_f, text="$0.00", bg="#111111", fg="#77ff99",
                                font=("Consolas", 11, "bold"))
        self.lbl_ask.pack(anchor="w")

        # RIGHT: P&L
        pnl_f = tk.Frame(top, bg="#111111")
        pnl_f.pack(side="right", padx=20)
        tk.Label(pnl_f, text="TOTAL P&L", bg="#111111", fg="#444",
                 font=("Consolas", 8)).pack(anchor="e")
        self.lbl_pnl = tk.Label(pnl_f, text="$0.00", bg="#111111", fg="#00ff00",
                                font=("Consolas", 20, "bold"))
        self.lbl_pnl.pack(anchor="e")
        tk.Label(pnl_f, text="DAILY", bg="#111111", fg="#444",
                 font=("Consolas", 7)).pack(anchor="e", pady=(4, 0))
        self.lbl_daily_pnl = tk.Label(pnl_f, text="$0.00", bg="#111111", fg="#888888",
                                      font=("Consolas", 10))
        self.lbl_daily_pnl.pack(anchor="e")

        tk.Frame(top, bg="#2a2a2a", width=1).pack(side="right", fill="y", padx=14, pady=6)

        # Metrics cluster: Positions | VIX | Circuit | Cash
        met_f = tk.Frame(top, bg="#111111")
        met_f.pack(side="right")
        r0 = tk.Frame(met_f, bg="#111111"); r0.pack(anchor="e")
        r1 = tk.Frame(met_f, bg="#111111"); r1.pack(anchor="e", pady=(6, 0))

        tk.Label(r0, text="POSITIONS", bg="#111111", fg="#444",
                 font=("Consolas", 7)).pack(side="left", padx=(0, 4))
        self.lbl_pos_count = tk.Label(r0, text=f"0 / {self.max_positions}",
                                      bg="#111111", fg="#ffffff",
                                      font=("Consolas", 12, "bold"))
        self.lbl_pos_count.pack(side="left", padx=(0, 16))
        tk.Label(r0, text="VIX PROXY", bg="#111111", fg="#444",
                 font=("Consolas", 7)).pack(side="left", padx=(0, 4))
        self.lbl_vix = tk.Label(r0, text="0.0%", bg="#111111", fg="#ffaa44",
                                font=("Consolas", 12, "bold"))
        self.lbl_vix.pack(side="left")

        tk.Label(r1, text="CIRCUIT", bg="#111111", fg="#444",
                 font=("Consolas", 7)).pack(side="left", padx=(0, 4))
        self.lbl_circuit = tk.Label(r1, text="ARMED", bg="#111111", fg="#00ff00",
                                    font=("Consolas", 10, "bold"))
        self.lbl_circuit.pack(side="left", padx=(0, 16))
        tk.Label(r1, text="CASH RESERVE", bg="#111111", fg="#444",
                 font=("Consolas", 7)).pack(side="left", padx=(0, 4))
        self.lbl_reserve = tk.Label(r1, text="$100,000", bg="#111111", fg="#ffdd44",
                                    font=("Consolas", 10, "bold"))
        self.lbl_reserve.pack(side="left")

        # --- BUTTON BAR ---
        btn_bar = tk.Frame(root, bg="#0d0d0d")
        btn_bar.pack(fill="x")
        tk.Frame(btn_bar, bg="#1e1e1e", height=1).pack(fill="x")
        btn_inner = tk.Frame(btn_bar, bg="#0d0d0d")
        btn_inner.pack(side="right", padx=14, pady=5)

        self._is_paper = "paper-api" in ALPACA_BASE_URL
        self.btn_halt  = None
        self.btn_paper = None

        _btn_defs = [
            ("▶  FORCE BUY",  "#1a4d1a", "#2d8f2d", self.force_buy,       None),
            ("✕  SELL ALL",   "#4d1a1a", "#8f2d2d", self.kill_all,        None),
            ("⏸  HALT ALGO",  "#4d3300", "#8f6000", self.toggle_halt,     "halt"),
            ("◈  PAPER MODE" if self._is_paper else "◈  LIVE MODE",
                               "#1a2d4d" if self._is_paper else "#4d1a1a",
                               "#2d5090" if self._is_paper else "#880000",
                               self.toggle_paper_live, "paper"),
            ("⊗  QUIT",       "#330000", "#550000", self.force_quit,      None),
        ]
        for txt, bg_n, bg_a, cmd, tag in _btn_defs:
            b = tk.Button(btn_inner, text=txt, bg=bg_n, fg="#cccccc",
                          font=("Consolas", 8, "bold"), command=cmd,
                          relief="flat", padx=14, pady=6,
                          activebackground=bg_a, activeforeground="#ffffff",
                          cursor="hand2")
            b.pack(side="left", padx=3)
            if tag == "halt":  self.btn_halt  = b
            if tag == "paper": self.btn_paper = b
        tk.Frame(btn_inner, bg="#1e1e1e", width=1).pack(side="left", fill="y", padx=6)

        # --- SIGNAL CARDS BAR ---
        tk.Frame(root, bg="#1a1a1a", height=1).pack(fill="x")
        cards_bar = tk.Frame(root, bg="#0c0c0c")
        cards_bar.pack(fill="x")
        tk.Frame(root, bg="#1a1a1a", height=1).pack(fill="x")

        tk.Label(cards_bar, text="WATCHLIST", bg="#0c0c0c", fg="#252525",
                 font=("Consolas", 7, "bold")).pack(side="left", padx=(12, 8), pady=8)

        self._sig_cards = {}
        for sym in self.watched_symbols:
            # outer card frame (provides colored left-border via bg padding trick)
            outer = tk.Frame(cards_bar, bg="#252525", padx=1, pady=1, cursor="hand2")
            outer.pack(side="left", padx=4, pady=6)

            inner = tk.Frame(outer, bg="#141414", padx=10, pady=6, cursor="hand2")
            inner.pack(fill="both", expand=True)

            # bind all sub-widgets to chart switch
            for w in (outer, inner):
                w.bind("<Button-1>", lambda e, s=sym: self.switch_chart_symbol(s))
                w.bind("<Enter>", lambda e, w2=inner: w2.config(bg="#1c1c1c"))
                w.bind("<Leave>", lambda e, w2=inner, s=sym: w2.config(
                    bg="#141414" if s != self.chart_symbol else "#0d1e2e"))

            # ticker row
            top_row = tk.Frame(inner, bg="#141414", cursor="hand2")
            top_row.pack(anchor="w")
            top_row.bind("<Button-1>", lambda e, s=sym: self.switch_chart_symbol(s))

            lbl_sym = tk.Label(top_row, text=sym, bg="#141414", fg="#aaaaaa",
                               font=("Consolas", 9, "bold"), cursor="hand2")
            lbl_sym.pack(side="left")
            lbl_sym.bind("<Button-1>", lambda e, s=sym: self.switch_chart_symbol(s))

            lbl_dot = tk.Label(top_row, text=" ●", bg="#141414", fg="#2a2a2a",
                               font=("Consolas", 8), cursor="hand2")
            lbl_dot.pack(side="left")
            lbl_dot.bind("<Button-1>", lambda e, s=sym: self.switch_chart_symbol(s))

            # price
            lbl_price = tk.Label(inner, text="$---", bg="#141414", fg="#cccccc",
                                 font=("Consolas", 10, "bold"), cursor="hand2")
            lbl_price.pack(anchor="w")
            lbl_price.bind("<Button-1>", lambda e, s=sym: self.switch_chart_symbol(s))

            # signal + rsi row
            bot_row = tk.Frame(inner, bg="#141414", cursor="hand2")
            bot_row.pack(anchor="w")
            bot_row.bind("<Button-1>", lambda e, s=sym: self.switch_chart_symbol(s))

            lbl_sig = tk.Label(bot_row, text="WAIT", bg="#141414", fg="#3a3a3a",
                               font=("Consolas", 7), cursor="hand2")
            lbl_sig.pack(side="left")
            lbl_sig.bind("<Button-1>", lambda e, s=sym: self.switch_chart_symbol(s))

            lbl_rsi = tk.Label(bot_row, text="  —", bg="#141414", fg="#3a3a3a",
                               font=("Consolas", 7), cursor="hand2")
            lbl_rsi.pack(side="left")
            lbl_rsi.bind("<Button-1>", lambda e, s=sym: self.switch_chart_symbol(s))

            self._sig_cards[sym] = {
                "outer": outer, "inner": inner, "top_row": top_row, "bot_row": bot_row,
                "lbl_sym": lbl_sym, "lbl_dot": lbl_dot,
                "lbl_price": lbl_price, "lbl_sig": lbl_sig, "lbl_rsi": lbl_rsi,
            }

        # --- CHART (Price + RSI) ---
        self.fig    = Figure(figsize=(12, 4.6), dpi=100, facecolor='#0a0a0a')
        self.ax     = self.fig.add_subplot(211)
        self.ax_rsi = self.fig.add_subplot(212)
        self.fig.subplots_adjust(hspace=0.06, top=0.93, bottom=0.06,
                                 left=0.06, right=0.98)
        for ax in (self.ax, self.ax_rsi):
            ax.set_facecolor('#0c0c0c')
            ax.tick_params(colors='#555', labelsize=7)
            for sp in ('top', 'right'):
                ax.spines[sp].set_visible(False)
            ax.spines['bottom'].set_color('#2a2a2a')
            ax.spines['left'].set_color('#2a2a2a')
        self.ax.grid(color='#161616', linestyle='--', linewidth=0.6, alpha=0.8)
        self.canvas = FigureCanvasTkAgg(self.fig, master=root)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=0, pady=0)

        # --- NOTEBOOK TABS ---
        nb_style = ttk.Style()
        nb_style.configure("TNotebook",
                           background="#0a0a0a", borderwidth=0, tabmargins=[0, 0, 0, 0])
        nb_style.configure("TNotebook.Tab",
                           background="#111111", foreground="#555555",
                           font=("Consolas", 8, "bold"),
                           padding=[14, 5])
        nb_style.map("TNotebook.Tab",
                     background=[("selected", "#1a1a1a")],
                     foreground=[("selected", "#00ffaa")])
        nb_style.configure("Treeview",
                           background="#0d0d0d", foreground="#cccccc",
                           fieldbackground="#0d0d0d", rowheight=22,
                           font=("Consolas", 8))
        nb_style.configure("Treeview.Heading",
                           background="#141414", foreground="#666666",
                           font=("Consolas", 8, "bold"))
        nb_style.map("Treeview", background=[("selected", "#0d2d4a")])

        nb = ttk.Notebook(root)
        nb.pack(fill="x", padx=0, pady=0)

        for tab_name, builder in [
            ("  LOG  ",           self._build_log_tab),
            ("  POSITIONS  ",     self._build_positions_tab),
            ("  PERFORMANCE  ",   self._build_performance_tab),
            ("  TRADE HISTORY  ", self._build_trade_history_tab),
            ("  EQUITY CURVE  ",  self._build_equity_tab),
            ("  BACKTEST  ",      self._build_backtest_tab),
            ("  SETTINGS  ",      self._build_settings_tab),
        ]:
            frame = tk.Frame(nb, bg="#0a0a0a")
            nb.add(frame, text=tab_name)
            builder(frame)

        # --- INIT CLIENTS ---
        self.alpaca_historical = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        self.alpaca_trading    = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        self.alpaca_stream     = StockDataStream(ALPACA_API_KEY, ALPACA_SECRET_KEY)

        self.app = TradingApp(self)
        for target in [self.run_api, self.run_alpaca_stream, self.alpha_cycle,
                       self.ibkr_watchdog, self.vix_updater]:
            threading.Thread(target=target, daemon=True).start()

        FlaskDashboard(self).start()
        self._load_history()
        self._restore_positions()

    # =========================================================================
    # TAB BUILDERS
    # =========================================================================
    def _build_log_tab(self, p):
        self.console = scrolledtext.ScrolledText(
            p, height=7, bg="#050505", fg="#00cc55",
            font=("Consolas", 8), insertbackground="#00cc55",
            selectbackground="#1a3a1a", selectforeground="#00ff88",
            relief="flat", borderwidth=0, padx=10, pady=6)
        self.console.pack(fill="both", expand=True)

    def _build_positions_tab(self, p):
        cols = ("Symbol","Side","Entry","Current","Qty","Unrealized","Target","Stop","Hold")
        self.pos_tree = ttk.Treeview(p, columns=cols, show="headings", height=6)
        widths = (70,60,80,80,60,100,80,80,70)
        for col, w in zip(cols, widths):
            self.pos_tree.heading(col, text=col)
            self.pos_tree.column(col, width=w, anchor="center")
        self.pos_tree.tag_configure("long",  foreground="#00ff88")
        self.pos_tree.tag_configure("short", foreground="#ff6666")
        sb = ttk.Scrollbar(p, orient="vertical", command=self.pos_tree.yview)
        self.pos_tree.configure(yscrollcommand=sb.set)
        self.pos_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _build_performance_tab(self, p):
        # --- Metrics strip ---
        mf = tk.Frame(p, bg="#0a0a0a")
        mf.pack(fill="x", padx=20, pady=(10, 4))
        metrics = [("Trades",   "lbl_m_trades"),  ("Wins",    "lbl_m_wins"),
                   ("Losses",   "lbl_m_losses"),  ("Win Rate","lbl_m_winrate"),
                   ("Avg Win",  "lbl_m_avgwin"),  ("Avg Loss","lbl_m_avgloss"),
                   ("Sharpe",   "lbl_m_sharpe"),  ("Sortino", "lbl_m_sortino"),
                   ("Max DD",   "lbl_m_drawdown")]
        for i, (title, attr) in enumerate(metrics):
            tk.Label(mf, text=title, bg="#0a0a0a", fg="#555",
                     font=("Consolas", 8)).grid(row=0, column=i, padx=12, pady=(4,2), sticky="w")
            lbl = tk.Label(mf, text="--", bg="#0a0a0a", fg="#cccccc",
                           font=("Consolas", 12, "bold"))
            lbl.grid(row=1, column=i, padx=12, sticky="w")
            setattr(self, attr, lbl)

        # --- Separator ---
        tk.Frame(p, bg="#1a1a1a", height=1).pack(fill="x", padx=20, pady=(8, 4))

        # --- Time-of-Day header ---
        tod_hdr = tk.Frame(p, bg="#0a0a0a")
        tod_hdr.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(tod_hdr, text="TIME OF DAY  —  P&L by 30-min session slot",
                 bg="#0a0a0a", fg="#444444", font=("Consolas", 8, "bold")).pack(side="left")
        tk.Button(tod_hdr, text="↺ REFRESH", bg="#141414", fg="#666",
                  font=("Consolas", 7), relief="flat", padx=8, pady=2,
                  activebackground="#1e1e1e", activeforeground="#aaa",
                  cursor="hand2",
                  command=self._update_tod_chart).pack(side="left", padx=10)

        # --- Time-of-Day chart ---
        self.tod_fig = Figure(figsize=(10, 2.0), dpi=100, facecolor='#0a0a0a')
        self.tod_ax  = self.tod_fig.add_subplot(111)
        self.tod_ax.set_facecolor('#0c0c0c')
        for sp in ('top', 'right'):
            self.tod_ax.spines[sp].set_visible(False)
        self.tod_ax.spines['bottom'].set_color('#2a2a2a')
        self.tod_ax.spines['left'].set_color('#2a2a2a')
        self.tod_ax.tick_params(colors='#555', labelsize=7)
        self.tod_fig.subplots_adjust(left=0.07, right=0.98, top=0.84, bottom=0.22)
        self.tod_canvas = FigureCanvasTkAgg(self.tod_fig, master=p)
        self.tod_canvas.get_tk_widget().pack(fill="both", expand=True, padx=20, pady=(0, 6))

    def _build_trade_history_tab(self, p):
        cols = ("Time","Symbol","Side","Entry","Exit","Qty","P&L","Hold","Reason")
        self.trade_tree = ttk.Treeview(p, columns=cols, show="headings", height=7)
        widths = (100,70,55,80,80,55,90,60,65)
        for col, w in zip(cols, widths):
            self.trade_tree.heading(col, text=col)
            self.trade_tree.column(col, width=w, anchor="center")
        self.trade_tree.tag_configure("win",  foreground="#00ff00")
        self.trade_tree.tag_configure("loss", foreground="#ff4444")
        sb = ttk.Scrollbar(p, orient="vertical", command=self.trade_tree.yview)
        self.trade_tree.configure(yscrollcommand=sb.set)
        self.trade_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _build_equity_tab(self, p):
        self.eq_fig = Figure(figsize=(10,3), dpi=100, facecolor='#0a0a0a')
        self.eq_ax  = self.eq_fig.add_subplot(111)
        self.eq_ax.set_facecolor('#0f0f0f')
        for sp in ['top','right']:
            self.eq_ax.spines[sp].set_visible(False)
        self.eq_ax.spines['bottom'].set_color('#333')
        self.eq_ax.spines['left'].set_color('#333')
        self.eq_ax.tick_params(colors='#555', labelsize=8)
        self.eq_ax.set_title("Equity Curve (Cumulative P&L)", color="#555", fontsize=9)
        self.eq_canvas = FigureCanvasTkAgg(self.eq_fig, master=p)
        self.eq_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _build_backtest_tab(self, p):
        top_row = tk.Frame(p, bg="#0a0a0a")
        top_row.pack(fill="x", padx=16, pady=8)

        def _lbl(text):
            tk.Label(top_row, text=text, bg="#0a0a0a", fg="#666",
                     font=("Consolas", 8)).pack(side="left", padx=(10, 3))

        def _entry(var, w=5):
            tk.Entry(top_row, textvariable=var, bg="#141414", fg="white",
                     font=("Consolas", 9), insertbackground="white",
                     relief="flat", width=w).pack(side="left")

        _lbl("Days back:")
        self.bt_days = tk.StringVar(value="5")
        _entry(self.bt_days)

        _lbl("Slippage %:")
        self.bt_slippage = tk.StringVar(value="0.05")
        _entry(self.bt_slippage, w=6)

        tk.Button(top_row, text="▶  RUN BACKTEST", bg="#004488", fg="white",
                  font=("Consolas", 8, "bold"), command=self.run_backtest,
                  relief="flat", padx=14, pady=5,
                  activebackground="#2d6db8", cursor="hand2").pack(side="left", padx=12)

        self.bt_status_lbl = tk.Label(top_row, text="", bg="#0a0a0a", fg="#666",
                                      font=("Consolas", 8))
        self.bt_status_lbl.pack(side="left")
        self.bt_out = scrolledtext.ScrolledText(p, height=8, bg="#000", fg="#00dd00",
                                                font=("Consolas",8))
        self.bt_out.pack(fill="both", expand=True, padx=16, pady=4)

    def _build_settings_tab(self, p):
        f = tk.Frame(p, bg="#0a0a0a")
        f.pack(fill="both", expand=True, padx=20, pady=8)
        params = [
            ("TP %",         "tp_pct",          self.tp_pct),
            ("SL %",         "sl_pct",          self.sl_pct),
            ("Trail %",      "trail_pct",        self.trail_pct),
            ("RSI Min",      "rsi_min",          self.rsi_min),
            ("RSI Max",      "rsi_max",          self.rsi_max),
            ("Vol Thresh",   "vol_threshold",    self.vol_threshold),
            ("Hold Min",     "hold_time_minutes",self.hold_time_minutes),
            ("Daily Limit",  "daily_loss_limit", self.daily_loss_limit),
            ("Max Pos",      "max_positions",    self.max_positions),
            ("VIX Pause %",  "vix_pause_threshold", self.vix_pause_threshold),
        ]
        self._param_vars = {}
        for i, (label, attr, default) in enumerate(params):
            tk.Label(f, text=label, bg="#0a0a0a", fg="#888",
                     font=("Consolas",8)).grid(row=0, column=i, padx=10, pady=(4,2), sticky="w")
            var = tk.StringVar(value=str(default))
            self._param_vars[attr] = var
            tk.Entry(f, textvariable=var, bg="#1a1a1a", fg="white",
                     font=("Consolas",9), insertbackground="white",
                     width=9).grid(row=1, column=i, padx=10)

        # Shorts toggle
        self.shorts_var = tk.BooleanVar(value=self.allow_shorts)
        tk.Checkbutton(f, text="Allow Shorts", variable=self.shorts_var,
                       bg="#0a0a0a", fg="#888", selectcolor="#1a1a1a",
                       activebackground="#0a0a0a", activeforeground="#ccc",
                       font=("Consolas",9)).grid(row=1, column=len(params)+1, padx=12)

        tk.Button(f, text="APPLY", bg="#004488", fg="white",
                  font=("Arial",9,"bold"), command=self._apply_settings,
                  padx=12, pady=4).grid(row=1, column=len(params)+2, padx=12)

    def _apply_settings(self):
        try:
            for attr, var in self._param_vars.items():
                val = float(var.get())
                if attr == "max_positions":
                    self.max_positions = int(val)
                else:
                    setattr(self, attr, val)
            self.allow_shorts = self.shorts_var.get()
            self.log(f"[SETTINGS] Applied — TP={self.tp_pct}% SL={self.sl_pct}% "
                     f"Trail={self.trail_pct}% RSI={self.rsi_min}-{self.rsi_max} "
                     f"Vol>{self.vol_threshold} Hold={self.hold_time_minutes}min "
                     f"Shorts={'ON' if self.allow_shorts else 'OFF'}")
        except ValueError as e:
            self.log(f"[SETTINGS ERROR] {e}")

    # =========================================================================
    # DATABASE
    # =========================================================================
    def _init_db(self):
        con = sqlite3.connect(str(self.db_path))
        con.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT,
                symbol      TEXT,
                side        TEXT,
                entry_price REAL,
                exit_price  REAL,
                qty         INTEGER,
                pnl         REAL,
                hold_min    REAL,
                exit_reason TEXT
            )""")
        con.execute("""
            CREATE TABLE IF NOT EXISTS open_positions (
                symbol        TEXT PRIMARY KEY,
                side          TEXT,
                entry_price   REAL,
                qty           INTEGER,
                target        REAL,
                stop_loss     REAL,
                highest_price REAL,
                lowest_price  REAL,
                open_time     REAL,
                atr           REAL
            )""")
        con.commit()
        con.close()

    def _save_trade(self, symbol, side, entry, exit_p, qty, pnl, hold_min, reason):
        try:
            con = sqlite3.connect(str(self.db_path))
            con.execute(
                "INSERT INTO trades VALUES (NULL,?,?,?,?,?,?,?,?,?)",
                (datetime.now(ET).isoformat(), symbol, side,
                 entry, exit_p, qty, pnl, hold_min, reason))
            con.commit()
            con.close()
        except Exception as e:
            self.log(f"[DB ERROR] {e}")

    def _save_open_position(self, symbol, pos):
        """Upsert a position into open_positions so it survives a crash/restart."""
        try:
            con = sqlite3.connect(str(self.db_path))
            con.execute(
                "INSERT OR REPLACE INTO open_positions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (symbol, pos['side'], pos['entry_price'], pos['qty'],
                 pos['target'], pos['stop_loss'],
                 pos['highest_price'], pos['lowest_price'],
                 pos['open_time'], pos['atr']))
            con.commit()
            con.close()
        except Exception as e:
            self.log(f"[DB] Position save error: {e}")

    def _remove_open_position(self, symbol):
        """Delete a position from open_positions once it is fully closed."""
        try:
            con = sqlite3.connect(str(self.db_path))
            con.execute("DELETE FROM open_positions WHERE symbol=?", (symbol,))
            con.commit()
            con.close()
        except Exception as e:
            self.log(f"[DB] Position remove error: {e}")

    def _restore_positions(self):
        """On startup: reload any positions that were open when the app last closed."""
        try:
            con  = sqlite3.connect(str(self.db_path))
            rows = con.execute(
                "SELECT symbol, side, entry_price, qty, target, stop_loss, "
                "highest_price, lowest_price, open_time, atr FROM open_positions"
            ).fetchall()
            con.close()
        except Exception as e:
            self.log(f"[DB] Could not restore positions: {e}")
            return

        if not rows:
            return

        with self.positions_lock:
            for sym, side, entry, qty, target, stop, high, low, open_t, atr in rows:
                self.positions[sym] = {
                    'side':          side,
                    'entry_price':   entry,
                    'qty':           qty,
                    'target':        target,
                    'stop_loss':     stop,
                    'highest_price': high,
                    'lowest_price':  low,
                    'open_time':     open_t,
                    'atr':           atr,
                }

        syms = [r[0] for r in rows]
        self.log(f"[RECOVERY] Restored {len(rows)} open position(s): {', '.join(syms)} "
                 f"— monitoring resumed.")
        self.send_alert("Positions Restored After Restart",
                        f"Resuming live monitoring: {', '.join(syms)}")

    def _load_history(self):
        """On startup: replay all trades from SQLite to rebuild P&L state and populate UI."""
        try:
            con  = sqlite3.connect(str(self.db_path))
            rows = con.execute(
                "SELECT timestamp, symbol, side, entry_price, exit_price, "
                "qty, pnl, hold_min, exit_reason FROM trades ORDER BY id ASC"
            ).fetchall()
            con.close()
        except Exception as e:
            self.log(f"[DB] Could not load history: {e}")
            return

        if not rows:
            return

        today_str   = date.today().isoformat()
        running_pnl = 0.0

        for ts, symbol, side, entry, exit_p, qty, pnl, hold_min, reason in rows:
            # --- Rebuild all counters / metrics ---
            self.trade_count += 1
            ret = pnl / (entry * qty) if entry * qty != 0 else 0.0
            self.trade_returns.append(ret)
            if pnl >= 0:
                self.win_count   += 1
                self.gross_wins  += pnl
            else:
                self.loss_count  += 1
                self.gross_losses += abs(pnl)

            running_pnl += pnl

            # Only today's trades count toward daily P&L
            if ts and ts[:10] == today_str:
                self.daily_pnl += pnl

            # Equity curve data point
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                dt = datetime.now()
            self.pnl_history.append((dt, running_pnl))

            # Treeview — insert at index 0 so newest ends up at the top
            tag = "win" if pnl >= 0 else "loss"
            self.trade_tree.insert("", 0, values=(
                ts[:19] if ts else "--", symbol, side,
                f"${entry:.2f}", f"${exit_p:.2f}", qty,
                f"${pnl:+.2f}", f"{hold_min:.1f}m", reason or "--"
            ), tags=(tag,))

        # Set totals
        self.total_pnl = running_pnl

        # Recompute peak + max drawdown from full equity curve
        if self.pnl_history:
            vals      = np.array([p for _, p in self.pnl_history], dtype=float)
            self.peak_pnl    = float(np.max(vals))
            peak_arr         = np.maximum.accumulate(vals)
            self.max_drawdown = float(np.max(peak_arr - vals))

        self.log(
            f"[DB] Loaded {len(rows)} historical trades | "
            f"All-time P&L: ${self.total_pnl:,.2f} | "
            f"Win rate: {(self.win_count/self.trade_count*100):.1f}%"
            if self.trade_count else f"[DB] Loaded {len(rows)} historical trades")

        self.update_metrics_display()
        self._refresh_pnl_labels()
        self.update_equity_curve()
        self._update_tod_chart()

    def _refresh_pnl_labels(self):
        """Update P&L display labels from current state (no state mutation)."""
        color = "#00ff00" if self.total_pnl >= 0 else "#ff2222"
        self.lbl_pnl.config(text=f"${self.total_pnl:,.2f}", fg=color)
        dc = "#00ff00" if self.daily_pnl >= 0 else "#ff4444"
        self.lbl_daily_pnl.config(text=f"${self.daily_pnl:,.2f}", fg=dc)

    # =========================================================================
    # UTILITY
    # =========================================================================
    def log(self, msg):
        ts   = time.strftime('%H:%M:%S')
        self.console.insert(tk.END, f"[{ts}] {msg}\n")
        self.console.see(tk.END)
        try:
            with open(self.log_path, "a", newline="") as f:
                csv.writer(f).writerow([ts, msg])
        except Exception:
            pass

    def update_status(self, msg):
        self.lbl_status.config(text=msg)

    def update_pnl(self, amount):
        self.total_pnl += amount
        self.daily_pnl += amount
        color = "#00ff00" if self.total_pnl >= 0 else "#ff2222"
        self.lbl_pnl.config(text=f"${self.total_pnl:,.2f}", fg=color)
        dc = "#00ff00" if self.daily_pnl >= 0 else "#ff4444"
        self.lbl_daily_pnl.config(text=f"${self.daily_pnl:,.2f}", fg=dc)
        if self.total_pnl > self.peak_pnl:
            self.peak_pnl = self.total_pnl
        self.max_drawdown = max(self.max_drawdown, self.peak_pnl - self.total_pnl)
        self.pnl_history.append((datetime.now(), self.total_pnl))
        self.root.after(0, self.update_equity_curve)

    def record_trade(self, pnl, symbol, side, entry, exit_p, qty, hold_min, reason):
        self.trade_count += 1
        ret = pnl / (entry * qty) if entry * qty != 0 else 0
        self.trade_returns.append(ret)
        if pnl >= 0:
            self.win_count  += 1;  self.gross_wins   += pnl
        else:
            self.loss_count += 1;  self.gross_losses += abs(pnl)
        sh, so = self._calc_ratios()
        self._save_trade(symbol, side, entry, exit_p, qty, pnl, hold_min, reason)
        self.root.after(0, self.update_metrics_display)
        self.root.after(0, self.add_trade_to_history,
                        symbol, side, entry, exit_p, qty, pnl, hold_min, reason)
        self.root.after(200, self._update_tod_chart)

    def _calc_ratios(self):
        if len(self.trade_returns) < 3:
            return 0.0, 0.0
        r   = np.array(self.trade_returns, dtype=float)
        ann = np.sqrt(252 * 20)
        std = np.std(r)
        sh  = float((np.mean(r) / std) * ann) if std > 0 else 0.0
        neg = r[r < 0]
        so_std = np.std(neg) if len(neg) > 0 else 0.001
        so  = float((np.mean(r) / so_std) * ann)
        return round(sh, 2), round(so, 2)

    def update_metrics_display(self):
        wr  = (self.win_count / self.trade_count * 100) if self.trade_count > 0 else 0
        aw  = (self.gross_wins   / self.win_count)  if self.win_count  > 0 else 0
        al  = (self.gross_losses / self.loss_count) if self.loss_count > 0 else 0
        sh, so = self._calc_ratios()
        self.lbl_m_trades.config(text=str(self.trade_count), fg="#ccc")
        self.lbl_m_wins.config(text=str(self.win_count),     fg="#00ff00")
        self.lbl_m_losses.config(text=str(self.loss_count),  fg="#ff4444")
        self.lbl_m_winrate.config(text=f"{wr:.1f}%", fg="#00ffaa" if wr >= 50 else "#ff8800")
        self.lbl_m_avgwin.config(text=f"${aw:,.0f}",   fg="#00ff00")
        self.lbl_m_avgloss.config(text=f"${al:,.0f}",  fg="#ff4444")
        self.lbl_m_sharpe.config(text=str(sh),  fg="#ffaa44")
        self.lbl_m_sortino.config(text=str(so), fg="#ffaa44")
        self.lbl_m_drawdown.config(text=f"${self.max_drawdown:,.0f}", fg="#ff8800")

    def add_trade_to_history(self, symbol, side, entry, exit_p, qty, pnl, hold_min, reason):
        tag = "win" if pnl >= 0 else "loss"
        self.trade_tree.insert("", 0, values=(
            datetime.now().strftime("%H:%M:%S"), symbol, side,
            f"${entry:.2f}", f"${exit_p:.2f}", qty,
            f"${pnl:+.2f}", f"{hold_min:.1f}m", reason
        ), tags=(tag,))

    def update_equity_curve(self):
        if len(self.pnl_history) < 2:
            return
        self.eq_ax.clear()
        self.eq_ax.set_facecolor('#0f0f0f')
        times = [t for t, _ in self.pnl_history]
        pnls  = [p for _, p in self.pnl_history]
        self.eq_ax.plot(times, pnls, color='#00ffaa', linewidth=1.5)
        self.eq_ax.fill_between(times, pnls, 0,
                                where=[p >= 0 for p in pnls], alpha=0.08, color='#00ff00')
        self.eq_ax.fill_between(times, pnls, 0,
                                where=[p < 0  for p in pnls], alpha=0.08, color='#ff3333')
        self.eq_ax.axhline(y=0, color='#333', linewidth=0.8)
        self.eq_ax.set_ylabel("P&L ($)", color='#555', fontsize=8)
        self.eq_ax.tick_params(colors='#555', labelsize=7)
        for sp in ['top','right']:
            self.eq_ax.spines[sp].set_visible(False)
        self.eq_ax.spines['bottom'].set_color('#333')
        self.eq_ax.spines['left'].set_color('#333')
        self.eq_canvas.draw()

    def _update_tod_chart(self):
        """Query closed trades from DB and redraw the time-of-day P&L bar chart."""
        try:
            con  = sqlite3.connect(str(self.db_path))
            rows = con.execute("""
                SELECT
                    CAST(substr(timestamp, 12, 2) AS INTEGER)                    AS hr,
                    CASE WHEN CAST(substr(timestamp, 15, 2) AS INTEGER) >= 30
                         THEN 1 ELSE 0 END                                        AS half,
                    COUNT(*)                                                      AS n,
                    SUM(pnl)                                                      AS tot_pnl,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)                     AS wins
                FROM trades
                GROUP BY hr, half
                ORDER BY hr, half
            """).fetchall()
            con.close()
        except Exception:
            return

        # Keep only market-hours buckets (9:00 – 15:59)
        slots = [(hr, half, n, tot or 0, wins or 0)
                 for hr, half, n, tot, wins in rows
                 if 9 <= hr < 16]
        if not slots:
            return

        labels      = [f"{hr}:{'30' if half else '00'}" for hr, half, *_ in slots]
        pnls        = [s[3] for s in slots]
        counts      = [s[2] for s in slots]
        win_rates   = [(s[4] / s[2] * 100) if s[2] > 0 else 0 for s in slots]

        self.tod_ax.clear()
        self.tod_ax.set_facecolor('#0c0c0c')

        x      = list(range(len(labels)))
        colors = ['#1a6630' if p >= 0 else '#661a1a' for p in pnls]
        bars   = self.tod_ax.bar(x, pnls, color=colors, alpha=0.9,
                                 width=0.65, zorder=2)

        # Label each bar with trade-count and win-rate
        y_max = max(abs(p) for p in pnls) if pnls else 1
        for bar, n, wr, pnl_v in zip(bars, counts, win_rates, pnls):
            offset = y_max * 0.05
            va     = 'bottom' if pnl_v >= 0 else 'top'
            y      = bar.get_height() + (offset if pnl_v >= 0 else -offset)
            self.tod_ax.text(bar.get_x() + bar.get_width() / 2, y,
                             f"{n}t  {wr:.0f}%",
                             ha='center', va=va,
                             color='#555555', fontsize=6, fontfamily='Consolas')

        self.tod_ax.axhline(y=0, color='#333333', linewidth=0.8, zorder=1)
        self.tod_ax.set_xticks(x)
        self.tod_ax.set_xticklabels(labels, fontsize=7, color='#555555')
        self.tod_ax.set_ylabel('P&L ($)', color='#444', fontsize=7)
        self.tod_ax.tick_params(colors='#555', labelsize=7)
        for sp in ('top', 'right'):
            self.tod_ax.spines[sp].set_visible(False)
        self.tod_ax.spines['bottom'].set_color('#2a2a2a')
        self.tod_ax.spines['left'].set_color('#2a2a2a')
        self.tod_canvas.draw()

    def update_connection_display(self):
        self.lbl_ib_status.config(fg="#00ff00"     if self.ib_connected     else "#ff3333")
        self.lbl_alpaca_status.config(fg="#00ff00" if self.alpaca_connected else "#ff3333")

    def update_price_display(self):
        if self.chart_symbol in self.quote_data:
            d = self.quote_data[self.chart_symbol]
            self.lbl_symbol.config(text=self.chart_symbol)
            self.lbl_price.config(text=f"${d['price']:.2f}")
            self.lbl_bid.config(text=f"${d['bid']:.2f}")
            self.lbl_ask.config(text=f"${d['ask']:.2f}")

    def update_monitor_display(self):
        # --- Update signal cards ---
        for sym in self.watched_symbols:
            c = self._sig_cards.get(sym)
            if not c:
                continue
            sg     = self.stock_signals.get(sym, {})
            signal = sg.get('signal', 'WAIT')
            price  = sg.get('price',  0.0)
            rsi    = sg.get('rsi',    0.0)
            score  = sg.get('score',  0.0)

            with self.positions_lock:
                in_pos = sym in self.positions

            is_chart = (sym == self.chart_symbol)

            # Background per state
            if is_chart:
                bg      = "#0d1e2e"
                bdr     = "#1a4a6a"
            elif in_pos:
                bg      = "#1a1800"
                bdr     = "#5a5000"
            elif signal == "BUY":
                bg      = "#0a1a0d"
                bdr     = "#1a5c20"
            elif signal == "SELL":
                bg      = "#1a0a0a"
                bdr     = "#5c1a1a"
            else:
                bg      = "#141414"
                bdr     = "#252525"

            # Text colours
            sym_fg  = "#00ffaa" if is_chart else ("#4488ff" if in_pos else "#aaaaaa")
            dot_fg  = {"BUY": "#00ff88", "SELL": "#ff4444"}.get(signal,
                       "#4488ff" if in_pos else "#2a2a2a")
            sig_fg  = {"BUY": "#00ff88", "SELL": "#ff5555"}.get(signal, "#3a3a3a")
            rsi_fg  = "#ffaa44" if rsi >= 70 else ("#00ff88" if rsi <= 30 else "#555")

            price_str = f"${price:.2f}" if price > 0 else "$---"
            rsi_str   = f"  RSI:{rsi:.0f}" if rsi > 0 else "  RSI:—"

            c["outer"].config(bg=bdr)
            for w in ("inner", "top_row", "bot_row"):
                c[w].config(bg=bg)
            c["lbl_sym"].config(bg=bg, fg=sym_fg)
            c["lbl_dot"].config(bg=bg, fg=dot_fg)
            c["lbl_price"].config(bg=bg, text=price_str)
            c["lbl_sig"].config(bg=bg, text=signal, fg=sig_fg)
            c["lbl_rsi"].config(bg=bg, text=rsi_str, fg=rsi_fg)

        # --- Positions table ---
        self.pos_tree.delete(*self.pos_tree.get_children())
        with self.positions_lock:
            for sym, pos in self.positions.items():
                cur  = self.stock_signals.get(sym, {}).get('price', pos['entry_price'])
                mult = 1 if pos['side'] == 'LONG' else -1
                unr  = (cur - pos['entry_price']) * pos['qty'] * mult
                hold = (time.time() - pos['open_time']) / 60
                tag  = "long" if pos['side'] == 'LONG' else "short"
                self.pos_tree.insert("", "end", values=(
                    sym, pos['side'],
                    f"${pos['entry_price']:.2f}", f"${cur:.2f}", pos['qty'],
                    f"${unr:+.2f}", f"${pos['target']:.2f}",
                    f"${pos['stop_loss']:.2f}", f"{hold:.1f}m"
                ), tags=(tag,))

        with self.positions_lock:
            count = len(self.positions)
        self.lbl_pos_count.config(text=f"{count} / {self.max_positions}")

    def switch_chart_symbol(self, sym):
        self.chart_symbol = sym
        self.log(f"[CHART] Switched to {sym}")
        if sym in self.stock_trends:
            self.root.after(0, self.update_chart, self.stock_trends[sym].tail(60))

    def toggle_halt(self):
        self.trading_halted = not self.trading_halted
        self._update_halt_ui()
        self.log(f"[RISK] Trading {'HALTED' if self.trading_halted else 'RESUMED'} by user.")
        self.send_alert("Algo Halt Toggle",
                        f"Trading {'halted' if self.trading_halted else 'resumed'} manually.")

    def _update_halt_ui(self):
        if self.trading_halted:
            self.btn_halt.config(text="RESUME ALGO", bg="#006600")
            self.lbl_circuit.config(text="HALTED", fg="#ff3333")
        else:
            self.btn_halt.config(text="HALT ALGO",  bg="#aa6600")
            self.lbl_circuit.config(text="ARMED",   fg="#00ff00")

    def toggle_paper_live(self):
        """Switch between paper trading and live trading."""
        self._is_paper = not self._is_paper
        new_url = ("https://paper-api.alpaca.markets" if self._is_paper
                   else "https://api.alpaca.markets")
        self.alpaca_trading = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY,
                                            paper=self._is_paper)
        self.btn_paper.config(
            text="PAPER MODE" if self._is_paper else "LIVE MODE",
            bg="#004488"      if self._is_paper else "#880000")
        self.log(f"[MODE] Switched to {'PAPER' if self._is_paper else 'LIVE'} trading.")

    def reset_daily_pnl(self):
        self.daily_pnl = 0.0
        self.lbl_daily_pnl.config(text="$0.00", fg="#aaa")
        self._premarket_done = False
        self.log("[SYSTEM] New trading day — daily P&L reset.")

    # =========================================================================
    # POSITION LIFECYCLE CALLBACKS (called from main thread via root.after)
    # =========================================================================
    def on_position_opened(self, symbol, side, fill_price, qty):
        allocation = (self.etf_allocation if symbol in self.etf_symbols
                      else self.large_cap_allocation)
        atr = self.stock_signals.get(symbol, {}).get('atr', 0)

        if side == 'LONG':
            target    = fill_price * (1 + self.tp_pct   / 100)
            stop_loss = fill_price * (1 - self.sl_pct   / 100)
        else:  # SHORT
            target    = fill_price * (1 - self.tp_pct   / 100)
            stop_loss = fill_price * (1 + self.sl_pct   / 100)

        with self.positions_lock:
            self.positions[symbol] = {
                'side':          side,
                'entry_price':   fill_price,
                'qty':           qty,
                'target':        target,
                'stop_loss':     stop_loss,
                'highest_price': fill_price,
                'lowest_price':  fill_price,
                'open_time':     time.time(),
                'atr':           atr,
            }

        with self.positions_lock:
            self._save_open_position(symbol, self.positions[symbol])

        self.update_status(
            f"{side} {symbol} @ ${fill_price:.2f} | {qty} shares | "
            f"TP ${target:.2f} | Stop ${stop_loss:.2f}")
        self.send_alert(f"Position Opened: {symbol}",
                        f"{side} {qty} {symbol} @ ${fill_price:.2f}")

    def on_position_closed(self, symbol, side, fill_price, qty):
        with self.positions_lock:
            pos = self.positions.pop(symbol, None)
        if pos is None:
            return

        mult     = 1 if side == 'LONG' else -1
        pnl      = (fill_price - pos['entry_price']) * qty * mult
        hold_min = (time.time() - pos['open_time']) / 60

        self._remove_open_position(symbol)
        self.update_pnl(pnl)
        self.record_trade(pnl, symbol, side, pos['entry_price'], fill_price,
                          qty, hold_min, "CLOSED")
        self.update_status(f"CLOSED {symbol} | P&L ${pnl:+.2f}")
        self.send_alert(f"Position Closed: {symbol}",
                        f"{side} {qty} {symbol} @ ${fill_price:.2f} | P&L ${pnl:+.2f}")

    # =========================================================================
    # CONNECTIONS
    # =========================================================================
    def run_api(self):
        self.app.connect("127.0.0.1", 7497, clientId=25)
        self.app.run()

    def ibkr_watchdog(self):
        time.sleep(15)
        fails = 0
        while True:
            try:
                if not self.ib_connected or self.app.next_order_id is None:
                    fails += 1
                    backoff = min(60, 5 * fails)
                    self.log(f"[WATCHDOG] IBKR down. Reconnect #{fails} in {backoff}s...")
                    time.sleep(backoff)
                    try: self.app.disconnect()
                    except Exception: pass
                    time.sleep(2)
                    self.app = TradingApp(self)
                    threading.Thread(target=self.run_api, daemon=True).start()
                else:
                    fails = 0
            except Exception as e:
                self.log(f"[WATCHDOG ERROR] {e}")
            time.sleep(15)

    async def on_quote(self, data: Quote):
        mid = (data.bid_price + data.ask_price) / 2
        self.quote_data[data.symbol] = {
            'bid': data.bid_price, 'ask': data.ask_price,
            'price': mid, 'timestamp': data.timestamp
        }
        if data.symbol == self.chart_symbol:
            self.current_price = mid
            self.root.after(0, self.update_price_display)

    def run_alpaca_stream(self):
        self.log("[ALPACA] Connecting to Real-Time Quote Stream...")
        try:
            self.alpaca_stream.subscribe_quotes(self.on_quote, *self.watched_symbols)
            self.alpaca_connected = True
            self.root.after(0, self.update_connection_display)
            self.alpaca_stream.run()
        except Exception as e:
            self.alpaca_connected = False
            self.root.after(0, self.update_connection_display)
            print(f"[ALPACA STREAM ERROR] {e}")   # <-- add this
            self.log(f"[ALPACA STREAM ERROR] {e}")

    def vix_updater(self):
        """Periodically estimate realized volatility of SPY as a VIX proxy."""
        time.sleep(10)
        while True:
            try:
                req = StockBarsRequest(
                    symbol_or_symbols="SPY",
                    timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                    limit=30)
                bars = self.alpaca_historical.get_stock_bars(req).data.get("SPY", [])
                if len(bars) > 5:
                    closes  = np.array([b.close for b in bars], dtype=float)
                    returns = np.diff(np.log(closes))
                    rv      = float(np.std(returns) * np.sqrt(252 * 390) * 100)
                    self.vix_proxy = rv
                    color = "#00ff00" if rv < 15 else "#ffaa44" if rv < 25 else "#ff3333"
                    self.root.after(0, self.lbl_vix.config,
                                   {"text": f"{rv:.1f}%", "fg": color})
            except Exception:
                pass
            time.sleep(60)

    # =========================================================================
    # ALERTS
    # =========================================================================
    def send_alert(self, subject, body):
        sender    = os.getenv("EMAIL_SENDER")
        password  = os.getenv("EMAIL_PASSWORD")
        recipient = os.getenv("EMAIL_RECIPIENT")
        if not all([sender, password, recipient]):
            return
        def _send():
            try:
                msg = MIMEText(body)
                msg['Subject'] = f"[AlphaHunter] {subject}"
                msg['From']    = sender
                msg['To']      = recipient
                host = os.getenv("SMTP_HOST", "smtp.gmail.com")
                port = int(os.getenv("SMTP_PORT", 587))
                with smtplib.SMTP(host, port) as s:
                    s.starttls()
                    s.login(sender, password)
                    s.sendmail(sender, recipient, msg.as_string())
            except Exception as e:
                self.log(f"[EMAIL ERROR] {e}")
        threading.Thread(target=_send, daemon=True).start()

    # =========================================================================
    # MANUAL CONTROLS
    # =========================================================================
    def force_buy(self):
        if self.trading_halted:
            self.log("[BLOCKED] Algo is halted.")
            return
        sym = self.chart_symbol
        if sym in self.quote_data:
            price = self.quote_data[sym]['price']
            alloc = self.etf_allocation if sym in self.etf_symbols else self.large_cap_allocation
            atr   = self.stock_signals.get(sym, {}).get('atr', 0)
            qty   = self._atr_position_size(price, alloc, atr)
            self.log(f"!!! MANUAL BUY: {sym} {qty} shares @ ~${price:.2f}")
            self.execute_trade(sym, "BUY", "LONG", price=price, qty=qty)
        else:
            self.log("[ERROR] No quote data for FORCE BUY")

    def kill_all(self):
        self.log("!!! KILL SWITCH: Closing all positions !!!")
        with self.positions_lock:
            syms = list(self.positions.keys())
        for sym in syms:
            price = self.quote_data.get(sym, {}).get('price', 0)
            if price > 0:
                with self.positions_lock:
                    pos = self.positions.get(sym)
                if pos:
                    close_action = "SELL" if pos['side'] == 'LONG' else "BUY"
                    self.execute_trade(sym, close_action, pos['side'],
                                       price=price, qty=pos['qty'])

    def force_quit(self):
        self.log("!!! FORCE QUIT !!!")
        try: self.app.disconnect()
        except Exception: pass
        self.root.quit()
        self.root.destroy()
        exit(0)

    # =========================================================================
    # ANALYSIS ENGINE
    # =========================================================================
    def _check_news(self, sym):
        """Return False if there is recent negative news for the symbol."""
        if not NEWS_AVAILABLE:
            return True
        try:
            req  = NewsRequest(symbols=[sym], limit=5)
            news = self.alpaca_historical.get_news(req)
            articles = news.news if hasattr(news, 'news') else []
            for article in articles[:5]:
                headline = (article.headline or "").lower()
                for word in ["downgrade","miss","recall","fraud","lawsuit","cut","warning","crash"]:
                    if word in headline:
                        self.log(f"[NEWS] Skipping {sym}: '{article.headline[:60]}'")
                        return False
            return True
        except Exception:
            return True   # fail open

    def _analyze_symbol(self, sym):
        """Compute indicators on 1-min bars + 5-min trend confirmation."""
        try:
            rt_price = self.quote_data[sym]['price'] if sym in self.quote_data else None

            # --- 1-min bars (60 bars) ---
            req1  = StockBarsRequest(symbol_or_symbols=sym,
                                     timeframe=TimeFrame(1, TimeFrameUnit.Minute), limit=60)
            bars1 = self.alpaca_historical.get_stock_bars(req1).data.get(sym, [])
            if len(bars1) < 26:
                return None

            # --- 5-min bars (30 bars) for trend confirmation ---
            req5  = StockBarsRequest(symbol_or_symbols=sym,
                                     timeframe=TimeFrame(5, TimeFrameUnit.Minute), limit=30)
            bars5 = self.alpaca_historical.get_stock_bars(req5).data.get(sym, [])

            df = pd.DataFrame([{'Time': b.timestamp, 'Close': b.close,
                                 'High': b.high, 'Low': b.low, 'Volume': b.volume}
                                for b in bars1])

            # SMA-20 + Bollinger Bands
            df['SMA20'] = df['Close'].rolling(20).mean()
            std         = df['Close'].rolling(20).std()
            df['Upper'] = df['SMA20'] + std * 1.5
            df['Lower'] = df['SMA20'] - std * 1.5

            # RSI-14
            delta      = df['Close'].diff()
            gain       = delta.where(delta > 0,  0.0).rolling(14).mean()
            loss       = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
            df['RSI']  = 100 - (100 / (1 + gain / loss))

            # MACD (12,26,9)
            ema12             = df['Close'].ewm(span=12, adjust=False).mean()
            ema26             = df['Close'].ewm(span=26, adjust=False).mean()
            df['MACD']        = ema12 - ema26
            df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            df['MACD_Hist']   = df['MACD'] - df['MACD_Signal']

            # ATR-14
            df['TR']    = pd.concat([
                df['High'] - df['Low'],
                (df['High'] - df['Close'].shift()).abs(),
                (df['Low']  - df['Close'].shift()).abs()
            ], axis=1).max(axis=1)
            df['ATR14'] = df['TR'].rolling(14).mean()

            # VWAP (rolling 30-bar)
            df['TP']     = (df['High'] + df['Low'] + df['Close']) / 3
            df['CumTPV'] = (df['TP'] * df['Volume']).rolling(30).sum()
            df['CumVol'] = df['Volume'].rolling(30).sum()
            df['VWAP']   = df['CumTPV'] / df['CumVol']

            # Volume ratio
            df['AvgVol20'] = df['Volume'].rolling(20).mean()

            price_now    = rt_price if rt_price else float(df['Close'].iloc[-1])
            sma          = float(df['SMA20'].iloc[-1])
            rsi          = float(df['RSI'].iloc[-1])
            macd         = float(df['MACD'].iloc[-1])
            macd_sig     = float(df['MACD_Signal'].iloc[-1])
            macd_bullish = macd > macd_sig
            atr          = float(df['ATR14'].iloc[-1])
            vwap         = float(df['VWAP'].iloc[-1])
            avg_vol      = float(df['AvgVol20'].iloc[-1])
            cur_vol      = float(df['Volume'].iloc[-1])
            volume_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0

            if any(pd.isna(v) for v in [sma, rsi, macd, atr, vwap]):
                return None

            # 5-min trend: bullish if last 5-min close > its SMA10
            htf_bullish = True
            htf_bearish = True
            if len(bars5) >= 10:
                df5 = pd.DataFrame([{'Close': b.close} for b in bars5])
                df5['SMA10'] = df5['Close'].rolling(10).mean()
                if not pd.isna(df5['SMA10'].iloc[-1]):
                    htf_bullish = float(df5['Close'].iloc[-1]) > float(df5['SMA10'].iloc[-1])
                    htf_bearish = float(df5['Close'].iloc[-1]) < float(df5['SMA10'].iloc[-1])

            deviation = (price_now - sma) / sma * 100

            signal = 'WAIT'
            score  = 0

            # BUY: all confirmations align + above VWAP
            if (price_now > sma and price_now > vwap
                    and deviation > 0.2
                    and self.rsi_min < rsi < self.rsi_max
                    and volume_ratio > self.vol_threshold
                    and macd_bullish and htf_bullish):
                signal = 'BUY'
                score  = (deviation * 2.0) + ((rsi - 50) * 0.10) + (volume_ratio * 0.50)

            # SELL / SHORT signal
            elif (price_now < sma and price_now < vwap
                  and deviation < -0.5 and rsi < 50
                  and not macd_bullish and htf_bearish):
                signal = 'SELL'
                score  = abs(deviation) + ((50 - rsi) * 0.10)

            # Chart dataframe (only for currently displayed symbol)
            chart_df = None
            if sym == self.chart_symbol:
                df['Time'] = pd.to_datetime(df['Time'])
                df.set_index('Time', inplace=True)
                chart_df = df

            return {
                'signal':       signal,
                'price':        price_now,
                'sma':          sma,
                'vwap':         vwap,
                'deviation':    deviation,
                'rsi':          rsi,
                'macd_bullish': macd_bullish,
                'htf_bullish':  htf_bullish,
                'atr':          atr,
                'volume_ratio': volume_ratio,
                'score':        score,
                'df':           chart_df,
            }

        except Exception:
            return None

    def _atr_position_size(self, price, allocation, atr):
        base = int(allocation / price)
        if atr <= 0:
            return base
        max_risk = self.total_capital * 0.005
        return max(1, min(base, int(max_risk / atr)))

    def _premarket_scan(self):
        """Rank watchlist by overnight gap + pre-market volume before open."""
        self.log("[PRE-MKT] Running pre-market watchlist scan...")
        scores = {}
        for sym in self.watched_symbols:
            try:
                req  = StockBarsRequest(symbol_or_symbols=sym,
                                        timeframe=TimeFrame(5, TimeFrameUnit.Minute), limit=10)
                bars = self.alpaca_historical.get_stock_bars(req).data.get(sym, [])
                if len(bars) < 2:
                    continue
                gap = (bars[-1].close - bars[0].open) / bars[0].open * 100
                avg_v = np.mean([b.volume for b in bars[:-1]])
                vol_r = bars[-1].volume / avg_v if avg_v > 0 else 1.0
                scores[sym] = gap * vol_r
            except Exception:
                pass
        if scores:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            self.log("[PRE-MKT] Ranked by momentum: " +
                     " | ".join(f"{s}:{v:+.2f}" for s, v in ranked[:5]))
        self._premarket_done = True

    # =========================================================================
    # MAIN TRADING LOOP
    # =========================================================================
    def alpha_cycle(self):
        time.sleep(3)
        analysis_interval = 2
        last_analysis     = 0

        while True:
            try:
                # Daily reset
                today = date.today()
                if today != self.last_trade_date:
                    self.last_trade_date = today
                    self.root.after(0, self.reset_daily_pnl)

                # Pre-market scan (once per day, 9:00-9:25 ET)
                if is_premarket() and not self._premarket_done:
                    threading.Thread(target=self._premarket_scan, daemon=True).start()

                # Market hours guard
                if not is_market_open():
                    self.root.after(0, self.update_status, "MARKET CLOSED")
                    time.sleep(30)
                    continue

                # VIX proxy guard
                if self.vix_proxy > self.vix_pause_threshold and not self.trading_halted:
                    self.log(f"[VIX] Proxy vol {self.vix_proxy:.1f}% > "
                             f"{self.vix_pause_threshold:.0f}% threshold. Pausing.")
                    self.root.after(0, self.update_status,
                                   f"VIX PAUSE ({self.vix_proxy:.1f}%)")
                    time.sleep(60)
                    continue

                # Circuit breaker
                if self.daily_pnl <= self.daily_loss_limit and not self.trading_halted:
                    self.trading_halted = True
                    self.root.after(0, self._update_halt_ui)
                    self.log(f"[CIRCUIT] Daily loss limit hit. Halting.")
                    self.send_alert("Circuit Breaker Triggered",
                                    f"Daily P&L ${self.daily_pnl:,.2f} hit limit.")

                if self.trading_halted:
                    self.root.after(0, self.update_status, "ALGO HALTED")
                    time.sleep(5)
                    continue

                # Economic blackout
                blocked, event = near_economic_event()
                if blocked:
                    self.root.after(0, self.update_status, f"PAUSED: {event}")
                    time.sleep(60)
                    continue

                # --- Trailing stop update for all open positions ---
                with self.positions_lock:
                    pos_copy = dict(self.positions)

                for sym, pos in pos_copy.items():
                    cur = self.stock_signals.get(sym, {}).get('price', 0)
                    if cur <= 0:
                        continue
                    if pos['side'] == 'LONG':
                        if cur > pos['highest_price']:
                            pos['highest_price'] = cur
                            new_stop = cur * (1 - self.trail_pct / 100)
                            if new_stop > pos['stop_loss']:
                                pos['stop_loss'] = new_stop
                                self._save_open_position(sym, pos)
                    else:  # SHORT
                        if cur < pos['lowest_price']:
                            pos['lowest_price'] = cur
                            new_stop = cur * (1 + self.trail_pct / 100)
                            if new_stop < pos['stop_loss']:
                                pos['stop_loss'] = new_stop
                                self._save_open_position(sym, pos)

                current_time = time.time()

                if (current_time - last_analysis) > analysis_interval:
                    last_analysis = current_time
                    self.log(f"[SCAN] {len(self.watched_symbols)} stocks ↦ parallel analysis...")

                    best_signal = None
                    best_symbol = None
                    best_score  = 0

                    with ThreadPoolExecutor(max_workers=8) as ex:
                        futures = {ex.submit(self._analyze_symbol, s): s
                                   for s in self.watched_symbols}
                        for future in as_completed(futures):
                            sym = futures[future]
                            try:
                                result = future.result()
                                if result is None:
                                    continue
                                self.stock_signals[sym] = result

                                if sym == self.chart_symbol and result.get('df') is not None:
                                    self.stock_trends[sym] = result['df']
                                    self.root.after(0, self.update_chart, result['df'].tail(60))

                                signal = result['signal']
                                score  = result['score']

                                with self.positions_lock:
                                    already_open = sym in self.positions
                                    n_positions  = len(self.positions)

                                if (not already_open and score > best_score
                                        and n_positions < self.max_positions):
                                    if signal == 'BUY' or (signal == 'SELL' and self.allow_shorts):
                                        best_score  = score
                                        best_symbol = sym
                                        best_signal = signal

                                if signal == 'BUY':
                                    self.log(
                                        f"[SIG] {sym}: BUY "
                                        f"(${result['price']:.2f} | "
                                        f"SMA${result['sma']:.2f} VWAP${result['vwap']:.2f} | "
                                        f"RSI:{result['rsi']:.1f} | "
                                        f"MACD:{'↑' if result['macd_bullish'] else '↓'} | "
                                        f"HTF:{'↑' if result['htf_bullish'] else '↓'} | "
                                        f"Score:{score:.2f})")
                                elif signal == 'SELL' and already_open:
                                    self.log(f"[SIG] {sym}: SELL signal")

                            except Exception:
                                self.stock_signals[sym] = {
                                    'signal':'ERROR','price':0,'sma':0,
                                    'rsi':0,'volume_ratio':0,'score':0,
                                    'macd_bullish':False,'vwap':0,'atr':0}

                    self.root.after(0, self.update_monitor_display)

                    # --- Entry ---
                    if best_symbol and best_signal in ('BUY', 'SELL'):
                        sig   = self.stock_signals[best_symbol]
                        price = sig['price']
                        atr   = sig.get('atr', 0)
                        side  = 'LONG' if best_signal == 'BUY' else 'SHORT'

                        # News filter
                        if not self._check_news(best_symbol):
                            self.log(f"[NEWS FILTER] Skipping {best_symbol}")
                        else:
                            alloc  = (self.etf_allocation if best_symbol in self.etf_symbols
                                      else self.large_cap_allocation)
                            qty    = self._atr_position_size(price, alloc, atr)
                            action = 'BUY' if side == 'LONG' else 'SELL'
                            self.log(f"[ENTRY] {side} {best_symbol} "
                                     f"score={best_score:.2f} atr={atr:.3f} qty={qty}")
                            self.execute_trade(best_symbol, action, side,
                                               price=price, qty=qty)

                    # --- Exit check for all open positions ---
                    with self.positions_lock:
                        pos_copy = dict(self.positions)

                    for sym, pos in pos_copy.items():
                        cur    = self.stock_signals.get(sym, {}).get('price', 0)
                        signal = self.stock_signals.get(sym, {}).get('signal', 'WAIT')
                        if cur <= 0:
                            continue

                        hold_min = (time.time() - pos['open_time']) / 60
                        reason   = None

                        if pos['side'] == 'LONG':
                            if   cur >= pos['target']:                      reason = f"TP {self.tp_pct}%"
                            elif cur <= pos['stop_loss']:                   reason = "Trail Stop"
                            elif signal == 'SELL':                          reason = "Signal"
                            elif hold_min >= self.hold_time_minutes:        reason = "Time Limit"
                        else:  # SHORT
                            if   cur <= pos['target']:                      reason = f"TP {self.tp_pct}%"
                            elif cur >= pos['stop_loss']:                   reason = "Trail Stop"
                            elif signal == 'BUY':                           reason = "Signal"
                            elif hold_min >= self.hold_time_minutes:        reason = "Time Limit"

                        if reason:
                            close_action = "SELL" if pos['side'] == 'LONG' else "BUY"
                            self.log(f"[EXIT] {sym} ({pos['side']}) @ ${cur:.2f} | {reason}")
                            self.execute_trade(sym, close_action, pos['side'],
                                               price=cur, qty=pos['qty'])

                time.sleep(0.5)

            except Exception as e:
                self.log(f"[LOOP ERROR] {e}")
                time.sleep(1)

    # =========================================================================
    # CHARTING
    # =========================================================================
    def update_chart(self, df):
        self.ax.clear()
        self.ax.grid(color='#161616', linestyle='--', linewidth=0.6, alpha=0.8)
        x = range(len(df))

        # Dynamic title
        sig   = self.stock_signals.get(self.chart_symbol, {})
        price = sig.get('price', self.current_price)
        rsi   = sig.get('rsi',   0)
        signal= sig.get('signal','WAIT')
        sig_col = {'BUY': '#00ff88', 'SELL': '#ff5555'}.get(signal, '#555555')
        title = (f"{self.chart_symbol}   ${price:.2f}"
                 f"   RSI {rsi:.0f}"
                 f"   [{signal}]")
        self.ax.set_title(title, color=sig_col, fontsize=9,
                          loc='left', pad=5, fontfamily='Consolas')

        self.ax.plot(x, df['Close'], color='#00ffcc', linewidth=2,   label='Close',   zorder=3)
        self.ax.plot(x, df['SMA20'], color='#ff00ff', linewidth=1.2,
                     linestyle='--', label='SMA20', zorder=2)
        if 'VWAP' in df.columns:
            self.ax.plot(x, df['VWAP'], color='#ffaa00', linewidth=1.2,
                         linestyle='-.', label='VWAP', zorder=2)
        self.ax.fill_between(x, df['Lower'], df['Upper'],
                             color='#333', alpha=0.15, label='BB 1.5σ', zorder=1)
        self.ax.plot(x, df['Upper'], color='#555', linewidth=0.7, linestyle=':',alpha=0.6)
        self.ax.plot(x, df['Lower'], color='#555', linewidth=0.7, linestyle=':',alpha=0.6)

        # Position levels for chart_symbol
        with self.positions_lock:
            pos = self.positions.get(self.chart_symbol)
        if pos:
            self.ax.axhline(y=pos['entry_price'], color='#00ff00', linewidth=1.5,
                            alpha=0.8, label=f"Entry ${pos['entry_price']:.2f}")
            self.ax.axhline(y=pos['target'],      color='#ffaa00', linewidth=1.5,
                            linestyle='--', alpha=0.8, label=f"Target ${pos['target']:.2f}")
            self.ax.axhline(y=pos['stop_loss'],   color='#ff3333', linewidth=1.2,
                            linestyle='--', alpha=0.7, label=f"Stop ${pos['stop_loss']:.2f}")

        self.ax.set_ylabel('Price ($)', color='#444', fontsize=7)
        self.ax.set_facecolor('#0c0c0c')
        self.ax.tick_params(colors='#555', labelsize=7)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.ax.spines['bottom'].set_color('#2a2a2a')
        self.ax.spines['left'].set_color('#2a2a2a')
        leg = self.ax.legend(loc='upper left', facecolor='#0f0f0f',
                             edgecolor='#333', labelcolor='#ccc', fontsize=7)
        leg.get_frame().set_alpha(0.9)

        # RSI panel
        self.ax_rsi.clear()
        self.ax_rsi.set_facecolor('#0f0f0f')
        if 'RSI' in df.columns:
            self.ax_rsi.plot(x, df['RSI'], color='#ffaa00', linewidth=1.1, label='RSI-14')
            for lvl, col in [(70,'#ff3333'),(50,'#555'),(30,'#00ff88')]:
                self.ax_rsi.axhline(y=lvl, color=col, linestyle='--',
                                    linewidth=0.7, alpha=0.6)
            self.ax_rsi.fill_between(x, df['RSI'], 50,
                                     where=(df['RSI'] >= 50), alpha=0.07, color='#00ff88')
            self.ax_rsi.fill_between(x, df['RSI'], 50,
                                     where=(df['RSI'] <  50), alpha=0.07, color='#ff3333')
            self.ax_rsi.set_ylim(0, 100)
            self.ax_rsi.set_ylabel('RSI', color='#444', fontsize=7)
            self.ax_rsi.tick_params(colors='#555', labelsize=6)
            self.ax_rsi.spines['top'].set_visible(False)
            self.ax_rsi.spines['right'].set_visible(False)
            self.ax_rsi.spines['bottom'].set_color('#2a2a2a')
            self.ax_rsi.spines['left'].set_color('#2a2a2a')
            self.ax_rsi.set_facecolor('#0c0c0c')
            rl = self.ax_rsi.legend(loc='upper left', facecolor='#0f0f0f',
                                    edgecolor='#333', labelcolor='#ccc', fontsize=6)
            rl.get_frame().set_alpha(0.9)

        self.canvas.draw()

    # =========================================================================
    # BACKTESTING
    # =========================================================================
    def run_backtest(self):
        def _go():
            self.bt_status_lbl.config(text="Running...")
            self.bt_out.delete(1.0, tk.END)
            params = {k: getattr(self, k) for k in
                      ('tp_pct','sl_pct','trail_pct','rsi_min','rsi_max',
                       'vol_threshold','hold_time_minutes')}
            params['hold_minutes']  = params.pop('hold_time_minutes')
            params['slippage_pct']  = float(self.bt_slippage.get())
            try:
                days = int(self.bt_days.get())
                res  = BacktestEngine(self.alpaca_historical,
                                      self.watched_symbols, params).run(days)
                self.root.after(0, self._show_backtest_results, res)
            except Exception as e:
                self.root.after(0, lambda: self.bt_status_lbl.config(text=f"Error: {e}"))
        threading.Thread(target=_go, daemon=True).start()

    def _show_backtest_results(self, r):
        self.bt_status_lbl.config(text="Complete")
        o = self.bt_out
        o.delete(1.0, tk.END)
        sep = "=" * 60 + "\n"
        slip_pct  = float(self.bt_slippage.get())
        est_slip  = sum(
            (t['entry_price'] + t['exit_price']) * t['qty'] * (slip_pct / 100)
            for t in r.get('trades', [])
        )
        o.insert(tk.END, sep)
        o.insert(tk.END, f"BACKTEST — {self.bt_days.get()} trading days\n")
        o.insert(tk.END, sep + "\n")
        o.insert(tk.END, f"  Total Trades   : {r['total_trades']}\n")
        o.insert(tk.END, f"  Total P&L      : ${r['total_pnl']:,.2f}  (after slippage)\n")
        o.insert(tk.END, f"  Slippage       : {slip_pct:.3f}% per side"
                         f"  ≈  ${est_slip:,.2f} total cost\n")
        o.insert(tk.END, f"  Win Rate       : {r['win_rate']:.1f}%\n")
        o.insert(tk.END, f"  Avg Win        : ${r['avg_win']:.2f}\n")
        o.insert(tk.END, f"  Avg Loss       : ${r['avg_loss']:.2f}\n")
        o.insert(tk.END, f"  Sharpe Ratio   : {r['sharpe']:.2f}\n")
        o.insert(tk.END, f"  Max Drawdown   : ${r['max_drawdown']:,.2f}\n\n")
        o.insert(tk.END, f"--- TRADES (showing first 50) ---\n")
        for t in r.get('trades', [])[:50]:
            sign = "+" if t['pnl'] >= 0 else ""
            o.insert(tk.END,
                     f"  {t['symbol']:4s} | "
                     f"{t['entry_time'].strftime('%m/%d %H:%M')} → "
                     f"{t['exit_time'].strftime('%H:%M')} | "
                     f"${t['entry_price']:.2f}→${t['exit_price']:.2f} | "
                     f"{sign}${t['pnl']:.2f} | "
                     f"{t['exit_reason']:5s} | "
                     f"{t['hold_min']:.1f}m\n")

    # =========================================================================
    # ORDER EXECUTION
    # =========================================================================
    def execute_trade(self, symbol, action, side='LONG', type="LMT", price=0.0, qty=0):
        contract           = Contract()
        contract.symbol    = symbol
        contract.secType   = "STK"
        contract.exchange  = "SMART"
        contract.currency  = "USD"

        order              = Order()
        order.action       = action
        order.orderType    = type
        order.totalQuantity = qty if qty > 0 else 1
        order.transmit      = True
        order.eTradeOnly    = False
        order.firmQuoteOnly = False

        # Smart limit pricing
        if type == "LMT":
            q = self.quote_data.get(symbol, {})
            if action == "BUY":
                ask = q.get('ask', price)
                order.lmtPrice = round(ask * 1.0005, 2)
            else:
                bid = q.get('bid', price)
                order.lmtPrice = round(bid * 0.9995, 2)

        if not self.app.next_order_id:
            self.log(f"[ERROR] Not connected to IBKR — cannot place {action} {symbol}")
            return

        oid = self.app.next_order_id
        self.app.order_map[oid] = {'symbol': symbol, 'action': action, 'side': side}
        self.log(f"[ORDER] {action} {side} {symbol} @ ~${price:.2f} | QTY:{order.totalQuantity}")
        self.app.placeOrder(oid, contract, order)
        self.app.next_order_id += 1


if __name__ == "__main__":
    root = tk.Tk()
    gui  = AlphaHunterGUI(root)
    root.mainloop()
