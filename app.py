
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
        return False, "missing"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(",") if c.strip()]
    ok_any = False
    for cid in chat_ids:
        try:
            payload = {"chat_id": cid, "text": msg}
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                ok_any = True
        except:
            pass
    return ok_any, ""

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
def atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = tr1.combine(tr2, max).combine(tr3, max)
    return tr.rolling(period).mean()

def detect_divergence(price_series, indicator_series, lookback=30):
    try:
        recent_price = price_series[-lookback:]
        recent_ind = indicator_series[-lookback:]
        half = lookback // 2
        first_half_price = recent_price[:half]
        second_half_price = recent_price[half:]
        first_low_price = first_half_price.min()
        second_low_price = second_half_price.min()
        first_low_idx = first_half_price.idxmin()
        second_low_idx = second_half_price.idxmin()
        first_high_price = first_half_price.max()
        second_high_price = second_half_price.max()
        first_high_idx = first_half_price.idxmax()
        second_high_idx = second_half_price.idxmax()
        first_low_ind = indicator_series.loc[first_low_idx] if first_low_idx in indicator_series.index else recent_ind.iloc[0]
        second_low_ind = indicator_series.loc[second_low_idx] if second_low_idx in indicator_series.index else recent_ind.iloc[-1]
        first_high_ind = indicator_series.loc[first_high_idx] if first_high_idx in indicator_series.index else recent_ind.iloc[0]
        second_high_ind = indicator_series.loc[second_high_idx] if second_high_idx in indicator_series.index else recent_ind.iloc[-1]
        bullish_div = second_low_price < first_low_price * 0.999 and second_low_ind > first_low_ind
        bearish_div = second_high_price > first_high_price * 1.001 and second_high_ind < first_high_ind
        return bullish_div, bearish_div
    except:
        return False, False

@app.route("/")
def home():
    t = thai_now()
    return f"<h1>V72 NO BB - EMA+ATR ✅</h1><p>{t}</p><p>ตัด BB ออกแล้ว ใช้ EMA+ATR อย่างเดียว</p><p><a href='/force-send'>/force-send</a></p>", 200

@app.route("/ping")
def ping():
    return f"PONG {thai_now()} - V72 NO BB", 200

@app.route("/force-send")
@app.route("/check")
def check():
    try:
        msg = run_v72_once()
        return f"<h1>OK ส่งแล้ว</h1><pre>{msg}</pre>", 200
    except Exception as e:
        import traceback
        return f"Error: {e}<br><pre>{traceback.format_exc()}</pre>", 500

def run_v72_once():
    import ccxt
    import pandas as pd
    exchanges_to_try = ['okx', 'bybit', 'coinbase', 'kucoin', 'gateio', 'bitget']
    ohlcv = None
    used_ex = None
    for ex_id in exchanges_to_try:
        try:
            ex_class = getattr(ccxt, ex_id)
            ex = ex_class({'enableRateLimit': True})
            ohlcv = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)
            if ohlcv and len(ohlcv) > 100:
                used_ex = ex_id.upper()
                break
        except:
            continue
    if ohlcv is None:
        raise Exception("ดึงกราฟไม่ได้")

    df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
    df['EMA_12'] = ema(df['close'], 12)
    df['EMA_26'] = ema(df['close'], 26)
    df['EMA_200'] = ema(df['close'], 200)
    df['RSI'] = rsi(df['close'], 14)
    df['MACD'], df['MACD_S'], _ = macd(df['close'], 12, 26, 9)
    df['ATR'] = atr(df['high'], df['low'], df['close'], 14)

    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last['close']
    ema12, ema26, ema200 = last['EMA_12'], last['EMA_26'], last['EMA_200']
    rsi_v = last['RSI']
    macd_dif, macd_dea = last['MACD'], last['MACD_S']
    atr_v = last['ATR']

    ema_cross_up = ema12 > ema26 and prev['EMA_12'] <= prev['EMA_26']
    ema_cross_down = ema12 < ema26 and prev['EMA_12'] >= prev['EMA_26']
    macd_cross_up = macd_dif > macd_dea and prev['MACD'] <= prev['MACD_S']
    macd_cross_down = macd_dif < macd_dea and prev['MACD'] >= prev['MACD_S']
    above_200 = price > ema200
    below_200 = price < ema200

    bullish_rsi_div, bearish_rsi_div = detect_divergence(df['close'], df['RSI'], 30)
    bullish_macd_div, bearish_macd_div = detect_divergence(df['close'], df['MACD'], 30)

    long_score = sum([ema_cross_up, macd_cross_up, above_200, rsi_v > 45, bullish_rsi_div, bullish_macd_div])
    short_score = sum([ema_cross_down, macd_cross_down, below_200, rsi_v < 55, bearish_rsi_div, bearish_macd_div])

    t = thai_now()
    trend = "ขาขึ้น" if price > ema200 else "ขาลง"

    # ช่วงราคาแบบไม่ใช้ BB - ใช้ EMA + ATR อย่างเดียว
    # ซื้อถูก = ใกล้ EMA12 หรือ EMA200 ลบ ATR
    # ขายแพง = ใกล้ EMA12 บวก ATR

    if long_score >= 4:
        # ซื้อ - ต้องซื้อถูกกว่าหรือเท่าราคาปัจจุบัน
        buy_low = ema200 - atr_v  # แนวรับลึก
        if buy_low > price:
            buy_low = price - atr_v * 1.5
        buy_high = price
        buy_ideal = ema12 if ema12 < price and ema12 > ema200 else price * 0.998

        sell_target = price + atr_v * 2  # เป้าขายสูงกว่า

        title = "🟢 ซื้อ"
        msg = (
            f"V72 [{SYMBOL}] {title}\n"
            f"📅 {t}\n"
            f"💰 ตอนนี้ ${price:.2f} | {used_ex} | RSI {rsi_v:.0f}\n"
            f"\n"
            f"🎯 ควรซื้อที่\n"
            f"${buy_low:.2f} - ${buy_high:.2f}\n"
            f"เป้าเข้า ${buy_ideal:.2f} (EMA12)\n"
            f"\n"
            f"📈 ถือไปขาย ${sell_target:.2f} | {trend}\n"
            f"--------------------------------"
        )
    elif short_score >= 4:
        # ขาย - ต้องขายแพงกว่าหรือเท่าราคาปัจจุบัน
        sell_low = price
        sell_high = price + atr_v * 1.5
        sell_ideal = price

        buy_back = ema200

        title = "🔴 ขาย"
        msg = (
            f"V72 [{SYMBOL}] {title}\n"
            f"📅 {t}\n"
            f"💰 ตอนนี้ ${price:.2f} | {used_ex} | RSI {rsi_v:.0f}\n"
            f"\n"
            f"🎯 ควรขายที่\n"
            f"${sell_low:.2f} - ${sell_high:.2f}\n"
            f"เป้าขาย ${sell_ideal:.2f} ตอนนี้เลย\n"
            f"\n"
            f"📉 รอย่อซื้อใหม่ ${buy_back:.2f} (EMA200)\n"
            f"--------------------------------"
        )
    else:
        # ถือไว้
        buy_low = ema200 - atr_v * 0.5
        buy_high = ema12
        if buy_high > price:
            buy_high = price * 0.995

        sell_low = price * 1.005
        sell_high = ema12 + atr_v * 1.5
        if sell_low < price:
            sell_low = price * 1.005

        trend_msg = f"ยัง {trend} ถ้ามีของถือต่อ" if price > ema200 else "รอดูก่อน"

        title = "💎 ถือไว้"
        msg = (
            f"V72 [{SYMBOL}] {title}\n"
            f"📅 {t}\n"
            f"💰 ตอนนี้ ${price:.2f} | {used_ex} | RSI {rsi_v:.0f}\n"
            f"\n"
            f"{trend_msg}\n"
            f"\n"
            f"🎯 ถ้าจะซื้อ รอ\n"
            f"${buy_low:.2f} - ${buy_high:.2f} (EMA200-EMA12)\n"
            f"\n"
            f"🎯 ถ้าจะขาย รอ\n"
            f"${sell_low:.2f} - ${sell_high:.2f}\n"
            f"--------------------------------"
        )

    send_telegram(msg)
    return msg

def bot_loop():
    time.sleep(10)
    while True:
        try:
            run_v72_once()
        except:
            pass
        time.sleep(3600)

def keep_alive_loop():
    time.sleep(20)
    while True:
        try:
            requests.get(BASE_URL, timeout=10)
        except:
            pass
        time.sleep(600)

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=keep_alive_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
