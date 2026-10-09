
import os
import threading
import time
from datetime import datetime, timedelta
import pytz
from flask import Flask
import requests

app = Flask(__name__)
THAI_TZ = pytz.timezone('Asia/Bangkok')
UTC_TZ = pytz.utc
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
        except Exception as e:
            print(f"Telegram error: {e}")
    return ok_any, ""

def thai_now():
    return datetime.now(UTC_TZ).astimezone(THAI_TZ).strftime("%d/%m/%Y %H:%M:%S น. เวลาไทย")

def thai_from_ts(ts_ms):
    try:
        dt_utc = datetime.fromtimestamp(ts_ms/1000, tz=UTC_TZ)
        return dt_utc.astimezone(THAI_TZ).strftime("%d/%m %H:%M")
    except:
        return ""

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
    return f"<h1>V76 ON-TIME FIXED ✅</h1><p>{t}</p><p>ส่งตรงทุกชั่วโมง นาทีที่ 02 - แก้แท่ง 19:00 ไม่ส่ง</p><p><a href='/force-send'>/force-send</a> | <a href='/status'>/status</a></p>", 200

@app.route("/ping")
def ping():
    return f"PONG {thai_now()} - V76", 200

@app.route("/status")
def status():
    now = datetime.now(UTC_TZ).astimezone(THAI_TZ)
    next_run = now.replace(minute=2, second=0, microsecond=0)
    if now.minute >= 2:
        next_run = next_run + timedelta(hours=1)
    wait = (next_run - now).total_seconds()
    return f"Now: {thai_now()}<br>Next run: {next_run.strftime('%d/%m/%Y %H:%M:%S')}<br>Wait: {wait:.0f}s<br>V76 ON-TIME", 200

@app.route("/force-send")
@app.route("/check")
def check():
    try:
        msg = run_v76_once()
        return f"<h1>OK ส่งแล้ว V76</h1><pre>{msg}</pre>", 200
    except Exception as e:
        import traceback
        return f"Error: {e}<br><pre>{traceback.format_exc()}</pre>", 500

def run_v76_once():
    import ccxt
    import pandas as pd
    exchanges_to_try = ['okx', 'bybit', 'coinbase', 'kucoin', 'gateio', 'bitget']
    ohlcv = None
    used_ex = None
    last_error = ""
    for ex_id in exchanges_to_try:
        try:
            ex_class = getattr(ccxt, ex_id)
            ex = ex_class({'enableRateLimit': True})
            ohlcv = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)
            if ohlcv and len(ohlcv) > 100:
                used_ex = ex_id.upper()
                break
        except Exception as e:
            last_error = str(e)
            continue
    if ohlcv is None:
        raise Exception(f"ดึงกราฟไม่ได้: {last_error}")

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
    last_ts = last['ts']
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

    t_now = thai_now()
    t_candle = thai_from_ts(last_ts)
    trend = "ขาขึ้น" if price > ema200 else "ขาลง"

    if long_score >= 4:
        buy_low = min(ema200 - atr_v*0.5, price - atr_v)
        buy_high = price
        buy_ideal = min(ema12, price*0.998) if ema12 < price else price*0.998
        sell_target = price + atr_v*2
        upside_pct = (sell_target - price) / price * 100
        title = "🟢 ซื้อ"
        msg = (
            f"V76 [{SYMBOL}] {title}\n"
            f"📅 ส่ง {t_now}\n"
            f"🕐 แท่ง {t_candle} | {used_ex}\n"
            f"💰 ตอนนี้ ${price:.2f} | RSI {rsi_v:.0f}\n"
            f"\n"
            f"🎯 ควรซื้อที่\n"
            f"${buy_low:.2f} - ${buy_high:.2f}\n"
            f"เป้าเข้า ${buy_ideal:.2f} (EMA12)\n"
            f"\n"
            f"📈 ถือไปขาย ${sell_target:.2f} (+{upside_pct:.2f}%) | {trend}\n"
            f"--------------------------------"
        )
    elif short_score >= 4:
        sell_low = price
        sell_high = price + atr_v*1.5
        buy_back = ema200
        downside_pct = (price - buy_back) / price * 100
        title = "🔴 ขาย"
        msg = (
            f"V76 [{SYMBOL}] {title}\n"
            f"📅 ส่ง {t_now}\n"
            f"🕐 แท่ง {t_candle} | {used_ex}\n"
            f"💰 ตอนนี้ ${price:.2f} | RSI {rsi_v:.0f}\n"
            f"\n"
            f"🎯 ควรขายที่\n"
            f"${sell_low:.2f} - ${sell_high:.2f}\n"
            f"\n"
            f"📉 รอย่อซื้อใหม่ ${buy_back:.2f} (-{downside_pct:.2f}%)\n"
            f"--------------------------------"
        )
    else:
        buy_low = ema200 - atr_v*0.5
        buy_high = min(ema12, price*0.995)
        if buy_low > buy_high:
            buy_low, buy_high = buy_high, buy_low
        buy_high = min(buy_high, price*0.995)
        buy_low = min(buy_low, buy_high - 1)
        sell_low = max(price*1.005, ema12)
        sell_high = sell_low + atr_v*1.5
        dist_to_buy = (price - buy_high) / price * 100
        dist_to_sell = (sell_low - price) / price * 100
        trend_msg = f"ยัง {trend} ถ้ามีของถือต่อ" if price > ema200 else "รอดูก่อน"
        if dist_to_sell > dist_to_buy * 1.5:
            insight = f"💡 ไปขาย +{dist_to_sell:.2f}% ไกลกว่า ลงไปซื้อ -{dist_to_buy:.2f}%\n   → ยังมี Upside น่าถือ/ซื้อได้"
        elif dist_to_buy > dist_to_sell * 1.5:
            insight = f"💡 ลงไปซื้อ -{dist_to_buy:.2f}% ไกลกว่า ไปขาย +{dist_to_sell:.2f}%\n   → ใกล้แนวขายแล้ว ระวัง"
        else:
            insight = f"💡 ระยะพอๆกัน ซื้อ -{dist_to_buy:.2f}% / ขาย +{dist_to_sell:.2f}%"
        title = "💎 ถือไว้"
        msg = (
            f"V76 [{SYMBOL}] {title}\n"
            f"📅 ส่ง {t_now}\n"
            f"🕐 แท่ง {t_candle} | {used_ex}\n"
            f"💰 ตอนนี้ ${price:.2f} | RSI {rsi_v:.0f}\n"
            f"\n"
            f"{trend_msg}\n"
            f"\n"
            f"🎯 ถ้าจะซื้อ รอถูกกว่านี้\n"
            f"${buy_low:.2f} - ${buy_high:.2f} (ลงอีก {dist_to_buy:.2f}%)\n"
            f"\n"
            f"🎯 ถ้าจะขาย รอแพงกว่านี้\n"
            f"${sell_low:.2f} - ${sell_high:.2f} (ขึ้นอีก {dist_to_sell:.2f}%)\n"
            f"\n"
            f"{insight}\n"
            f"--------------------------------"
        )
    send_telegram(msg)
    print(f"[{t_now}] Sent: {title} {price}")
    return msg

def bot_loop():
    print("V76 bot_loop started - ON TIME scheduler")
    time.sleep(10)
    # ส่งครั้งแรกตอนบูตเลย
    try:
        run_v76_once()
    except Exception as e:
        print(f"First run failed: {e}")
    
    while True:
        try:
            now = datetime.now(UTC_TZ).astimezone(THAI_TZ)
            # คำนวณรอบถัดไป: นาทีที่ 02 ของชั่วโมงถัดไป
            next_run = now.replace(minute=2, second=0, microsecond=0)
            if now.minute >= 2:
                next_run = next_run + timedelta(hours=1)
            wait_seconds = (next_run - now).total_seconds()
            if wait_seconds < 0:
                wait_seconds += 3600
            if wait_seconds > 3600:
                wait_seconds = 3600
            
            print(f"[{thai_now()}] Next run at {next_run.strftime('%H:%M:%S')} in {wait_seconds:.0f}s")
            # นอนแบบสั้นๆ เพื่อไม่ให้ Render คิดว่า idle เกินไป
            while wait_seconds > 0:
                sleep_chunk = min(wait_seconds, 60)
                time.sleep(sleep_chunk)
                wait_seconds -= sleep_chunk
            
            print(f"[{thai_now()}] Running scheduled task...")
            run_v76_once()
        except Exception as e:
            print(f"bot_loop error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)

def keep_alive_loop():
    time.sleep(20)
    while True:
        try:
            if BASE_URL:
                r = requests.get(BASE_URL, timeout=10)
                print(f"Keep-alive ping: {r.status_code}")
        except Exception as e:
            print(f"Keep-alive failed: {e}")
        time.sleep(300)  # ทุก 5 นาที กันหลับ

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=keep_alive_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
