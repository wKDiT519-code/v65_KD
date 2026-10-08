
import os
import threading
import time
from datetime import datetime
import pytz
from flask import Flask
import requests

app = Flask(__name__)
THAI_TZ = pytz.timezone('Asia/Bangkok')
SYMBOL = "PAXG/USDT"
TIMEFRAME = "1h"
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://v65-kd.onrender.com")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(msg)
        return False, "TOKEN or CHAT ID missing"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        r = requests.post(url, json=payload, timeout=15)
        print(f"Telegram: {r.status_code}")
        return r.status_code == 200, r.text
    except Exception as e:
        print(f"TG error: {e}")
        return False, str(e)

def thai_now():
    return datetime.now(THAI_TZ).strftime("%d/%m/%Y %H:%M น. เวลาไทย")

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()
def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))
def macd(series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line
def bbands(series, period=20, std=2.0):
    sma = series.rolling(period).mean()
    std_dev = series.rolling(period).std()
    return sma, sma + std*std_dev, sma - std*std_dev
def atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = tr1.combine(tr2, max).combine(tr3, max)
    return tr.rolling(period).mean()

@app.route("/")
def home():
    t = thai_now()
    token_set = "SET ✅" if TELEGRAM_BOT_TOKEN else "NOT SET ❌"
    chat_set = "SET ✅" if TELEGRAM_CHAT_ID else "NOT SET ❌"
    return f"""
    <h1>V65 Binance Bot LIVE ✅ กันหลับแล้ว</h1>
    <p>PAXG/USDT 1H - {t}</p>
    <p>TOKEN: {token_set} | CHAT_ID: {chat_set}</p>
    <p><a href="/ping">/ping - กันหลับ</a> | <a href="/test-telegram">/test-telegram</a> | <a href="/check">/check</a></p>
    <p>Keep-Alive: ทุก 10 นาที + Bot Loop ทุก 60 นาที</p>
    """, 200

@app.route("/ping")
def ping():
    return f"PONG {thai_now()} - Bot Awake ✅", 200

@app.route("/test-telegram")
def test_telegram():
    t = thai_now()
    msg = f"V65 TEST 🟢 Telegram OK\n📅 {t}\nBot LIVE + กันหลับแล้ว ✅"
    ok, resp = send_telegram(msg)
    if ok:
        return f"<h1>✅ ส่งแล้ว</h1><p>{msg}</p>", 200
    else:
        return f"<h1>❌ ส่งไม่สำเร็จ</h1><p>Error: {resp}</p>", 500

@app.route("/check")
def check():
    try:
        msg = run_v65_once()
        return f"<pre>{msg}</pre>", 200
    except Exception as e:
        import traceback
        return f"Error: {e}<br><pre>{traceback.format_exc()}</pre>", 500

def run_v65_once():
    import ccxt
    import pandas as pd
    ex = ccxt.binance()
    ohlcv = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)
    df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
    df['EMA_12'] = ema(df['close'], 12)
    df['EMA_26'] = ema(df['close'], 26)
    df['EMA_200'] = ema(df['close'], 200)
    df['RSI'] = rsi(df['close'], 14)
    df['MACD'], df['MACD_S'], _ = macd(df['close'], 12, 26, 9)
    df['BOLL'], df['UB'], df['LB'] = bbands(df['close'], 20, 2.0)
    df['ATR'] = atr(df['high'], df['low'], df['close'], 14)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last['close']
    ema12, ema26, ema200 = last['EMA_12'], last['EMA_26'], last['EMA_200']
    rsi_v = last['RSI']
    macd_dif, macd_dea = last['MACD'], last['MACD_S']
    boll, ub, lb, atr_v = last['BOLL'], last['UB'], last['LB'], last['ATR']
    ema_cross_up = ema12 > ema26 and prev['EMA_12'] <= prev['EMA_26']
    ema_cross_down = ema12 < ema26 and prev['EMA_12'] >= prev['EMA_26']
    macd_cross_up = macd_dif > macd_dea and prev['MACD'] <= prev['MACD_S']
    macd_cross_down = macd_dif < macd_dea and prev['MACD'] >= prev['MACD_S']
    above_200 = price > ema200
    below_200 = price < ema200
    long_score = sum([ema_cross_up, macd_cross_up, above_200, rsi_v > 45])
    short_score = sum([ema_cross_down, macd_cross_down, below_200, rsi_v < 55])
    boll_info = f"BOLL {boll:.2f} UB {ub:.2f} LB {lb:.2f} EMA200 {ema200:.1f} ATR {atr_v:.2f}"
    def h_buy(): return "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n🟢🟢 <b>➡ SPOT ซื้อจ้า</b> 🟢🟢\n🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩"
    def h_sell(): return "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n🔴🔴 <b>➡ SPOT ขายจ้า</b> 🔴🔴\n🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥"
    def h_hold(): return "🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦\n💎💎 <b>✊ ถือไว้/รอก่อน</b> 💎💎\n🟨🟨 <b>⏳ รอสัญญาณชัดๆ</b> 🟨🟨\n🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦"
    t = thai_now()
    if long_score >= 3:
        info = h_buy() + f"\nLong {long_score}/4 RSI {rsi_v:.1f}"
        msg = f"V65_binance [{SYMBOL}] 🟢 ซื้อจ้า\n📅 {t}\n${price:.2f} {boll_info}\n{info}"
    elif short_score >= 3:
        info = h_sell() + f"\nShort {short_score}/4 RSI {rsi_v:.1f}"
        msg = f"V65_binance [{SYMBOL}] 🔴 ขายจ้า\n📅 {t}\n${price:.2f} {boll_info}\n{info}"
    else:
        info = h_hold() + f"\nLong {long_score}/4 Short {short_score}/4 RSI {rsi_v:.1f}"
        msg = f"V65_binance [{SYMBOL}] 💎 รอก่อน\n📅 {t}\n${price:.2f} {boll_info}\n{info}"
    send_telegram(msg)
    return msg

def bot_loop():
    print("🚀 V65 Bot Loop Started")
    time.sleep(15)
    while True:
        try:
            print(run_v65_once())
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(3600)

def keep_alive_loop():
    print("🛡️ Keep-Alive Started - กันหลับทุก 10 นาที")
    time.sleep(30)
    while True:
        try:
            # self ping
            r = requests.get(BASE_URL, timeout=10)
            print(f"Keep-Alive self-ping: {r.status_code} {thai_now()}")
            # ping /ping
            r2 = requests.get(f"{BASE_URL}/ping", timeout=10)
            print(f"Keep-Alive /ping: {r2.status_code}")
        except Exception as e:
            print(f"Keep-Alive error: {e}")
        time.sleep(600)  # 10 นาที

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=keep_alive_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
