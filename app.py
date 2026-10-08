
import os
import time
import threading
from datetime import datetime
import pytz

# Flask must be importable even if trading libs fail
try:
    from flask import Flask
    app = Flask(__name__)
except Exception as e:
    print(f"Flask import failed: {e}")
    raise

THAI_TZ = pytz.timezone('Asia/Bangkok')

@app.route("/")
def health():
    return f"V65 Binance Bot Running OK - {datetime.now(THAI_TZ).strftime('%d/%m/%Y %H:%M')} - PAXG/USDT 1H - Status: LIVE", 200

@app.route("/check")
def manual_check():
    try:
        msg = run_bot_once()
        return f"<pre>{msg}</pre>", 200
    except Exception as e:
        return f"Error: {e}", 500

def run_bot_once():
    try:
        import ccxt
        import pandas as pd
        import pandas_ta as ta
        import requests
        
        SYMBOL = "PAXG/USDT"
        TIMEFRAME = "1h"
        EMA_FAST, EMA_SLOW, EMA_TREND = 12, 26, 200
        MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
        RSI_PERIOD, BB_PERIOD, BB_STD, ATR_PERIOD = 14, 20, 2.0, 14
        THAI_TZ = pytz.timezone('Asia/Bangkok')
        TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
        
        def send_telegram(msg):
            if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
                print(msg)
                return
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            try:
                import requests
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
            except: pass
        
        ex = ccxt.binance()
        ohlcv = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)
        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
        df['EMA_12'] = ta.ema(df['close'], EMA_FAST)
        df['EMA_26'] = ta.ema(df['close'], EMA_SLOW)
        df['EMA_200'] = ta.ema(df['close'], EMA_TREND)
        macd = ta.macd(df['close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
        df = pd.concat([df, macd], axis=1)
        df['RSI'] = ta.rsi(df['close'], RSI_PERIOD)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], ATR_PERIOD)
        bb = ta.bbands(df['close'], length=BB_PERIOD, std=BB_STD)
        df['BOLL'] = bb[f'BBM_{BB_PERIOD}_{BB_STD}']
        df['UB'] = bb[f'BBU_{BB_PERIOD}_{BB_STD}']
        df['LB'] = bb[f'BBL_{BB_PERIOD}_{BB_STD}']
        
        last = df.iloc[-1]
        price = last['close']
        ema12 = last['EMA_12']
        ema26 = last['EMA_26']
        ema200 = last['EMA_200']
        rsi = last['RSI']
        
        # Simple logic
        if ema12 > ema26 and price > ema200 and rsi > 45:
            msg = f"V65 [PAXG/USDT] 🟢 SPOT ซื้อจ้า\nราคา ${price:.2f} RSI {rsi:.1f}\n🟩🟩🟩➡ ซื้อจ้า 🟩🟩🟩"
        elif ema12 < ema26 and price < ema200 and rsi < 55:
            msg = f"V65 [PAXG/USDT] 🔴 SPOT ขายจ้า\nราคา ${price:.2f} RSI {rsi:.1f}\n🟥🟥🟥➡ ขายจ้า 🟥🟥🟥"
        else:
            msg = f"V65 [PAXG/USDT] 💎 ถือไว้/รอก่อน\nราคา ${price:.2f} EMA12 {ema12:.1f} EMA26 {ema26:.1f} EMA200 {ema200:.1f} RSI {rsi:.1f}\n🟦ถือไว้/รอก่อน🟦"
        
        send_telegram(msg)
        return msg
    except Exception as e:
        err = f"Bot error: {e}"
        print(err)
        return err

def bot_loop():
    print("🚀 V65 Bot Loop Started - PAXG/USDT 1H")
    # รอ Flask bind port ก่อน 10 วิ
    time.sleep(10)
    while True:
        try:
            print(run_bot_once())
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(3600)

# Start bot in background
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
