
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
        print(f"Missing TOKEN/CHAT_ID: {msg}")
        return False, "TOKEN or CHAT ID missing"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(",") if c.strip()]
    ok_any = False
    last_resp = ""
    for cid in chat_ids:
        try:
            payload = {"chat_id": cid, "text": msg}
            r = requests.post(url, json=payload, timeout=15)
            print(f"Telegram -> {cid}: {r.status_code}")
            last_resp = r.text
            if r.status_code == 200:
                ok_any = True
        except Exception as e:
            print(f"TG error {cid}: {e}")
            last_resp = str(e)
    return ok_any, last_resp

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

# === DIVERGENT DETECTION ===
def detect_divergence(price_series, indicator_series, lookback=30):
    """
    ตรวจ Bullish/Bearish Divergence แบบง่าย
    Bullish: ราคาทำ Low ต่ำลง แต่ Indicator ทำ Low สูงขึ้น
    Bearish: ราคาทำ High สูงขึ้น แต่ Indicator ทำ High ต่ำลง
    """
    try:
        import pandas as pd
        # ใช้ 30 แท่งล่าสุด
        recent_price = price_series[-lookback:]
        recent_ind = indicator_series[-lookback:]

        # หา Low 2 จุดล่าสุด
        # แบ่งครึ่ง lookback หา low แต่ละครึ่ง
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

        # RSI / MACD ณ จุด low/high นั้นๆ
        first_low_ind = indicator_series.loc[first_low_idx] if first_low_idx in indicator_series.index else recent_ind.iloc[0]
        second_low_ind = indicator_series.loc[second_low_idx] if second_low_idx in indicator_series.index else recent_ind.iloc[-1]
        first_high_ind = indicator_series.loc[first_high_idx] if first_high_idx in indicator_series.index else recent_ind.iloc[0]
        second_high_ind = indicator_series.loc[second_high_idx] if second_high_idx in indicator_series.index else recent_ind.iloc[-1]

        bullish_div = False
        bearish_div = False

        # Bullish: ราคาต่ำลง แต่ indicator สูงขึ้น (อย่างน้อย 2%)
        if second_low_price < first_low_price * 0.999 and second_low_ind > first_low_ind:
            bullish_div = True

        # Bearish: ราคาสูงขึ้น แต่ indicator ต่ำลง
        if second_high_price > first_high_price * 1.001 and second_high_ind < first_high_ind:
            bearish_div = True

        return bullish_div, bearish_div, {
            'first_low_price': float(first_low_price),
            'second_low_price': float(second_low_price),
            'first_low_ind': float(first_low_ind),
            'second_low_ind': float(second_low_ind),
            'first_high_price': float(first_high_price),
            'second_high_price': float(second_high_price),
            'first_high_ind': float(first_high_ind),
            'second_high_ind': float(second_high_ind),
        }
    except Exception as e:
        print(f"Div detect error: {e}")
        return False, False, {}

@app.route("/")
def home():
    t = thai_now()
    return f"""
    <h1>V66 Bot LIVE - EMA+MACD+RSI+DIVERGENT ✅</h1>
    <p>PAXG/USDT 1H - {t}</p>
    <p>กลยุทธ: EMA12/26 + MACD + EMA200 + RSI + RSI Div + MACD Div (6 ปัจจัย ต้องได้ 4/6)</p>
    <p><a href="/ping">/ping</a> | <a href="/test-telegram">/test-telegram</a> | <a href="/force-send">/force-send</a></p>
    """, 200

@app.route("/ping")
def ping():
    return f"PONG {thai_now()} - V66 DIVERGENT Bot Awake", 200

@app.route("/test-telegram")
def test_telegram():
    t = thai_now()
    msg = f"V66 TEST ✅ EMA+MACD+RSI+Divergent\n{t}\nBot LIVE"
    ok, resp = send_telegram(msg)
    if ok:
        return f"<h1>OK ส่งแล้ว</h1><pre>{msg}</pre>", 200
    else:
        return f"<h1>FAIL</h1><p>{resp}</p>", 500

@app.route("/force-send")
@app.route("/check")
def check():
    try:
        msg = run_v66_once()
        return f"<h1>OK ส่งแล้ว</h1><pre>{msg}</pre>", 200
    except Exception as e:
        import traceback
        return f"Error: {e}<br><pre>{traceback.format_exc()}</pre>", 500

def run_v66_once():
    import ccxt
    import pandas as pd
    exchanges_to_try = ['okx', 'bybit', 'coinbase', 'kucoin', 'gateio', 'bitget']
    ohlcv = None
    used_ex = None
    last_error = None
    for ex_id in exchanges_to_try:
        try:
            ex_class = getattr(ccxt, ex_id)
            ex = ex_class({'enableRateLimit': True})
            ohlcv = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)
            if ohlcv and len(ohlcv) > 100:
                used_ex = ex_id.upper()
                print(f"Use {ex_id} OK")
                break
        except Exception as e:
            print(f"{ex_id} fail: {e}")
            last_error = e
            continue
    if ohlcv is None:
        raise Exception(f"ดึงกราฟไม่ได้: {last_error}")

    df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
    df['EMA_12'] = ema(df['close'], 12)
    df['EMA_26'] = ema(df['close'], 26)
    df['EMA_200'] = ema(df['close'], 200)
    df['RSI'] = rsi(df['close'], 14)
    df['MACD'], df['MACD_S'], df['MACD_H'] = macd(df['close'], 12, 26, 9)
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
    rsi_long = rsi_v > 45
    rsi_short = rsi_v < 55

    # === DIVERGENT ===
    bullish_rsi_div, bearish_rsi_div, rsi_div_info = detect_divergence(df['close'], df['RSI'], lookback=30)
    bullish_macd_div, bearish_macd_div, macd_div_info = detect_divergence(df['close'], df['MACD'], lookback=30)

    long_score = sum([ema_cross_up, macd_cross_up, above_200, rsi_long, bullish_rsi_div, bullish_macd_div])
    short_score = sum([ema_cross_down, macd_cross_down, below_200, rsi_short, bearish_rsi_div, bearish_macd_div])

    t = thai_now()

    # สร้างรายละเอียด Divergent สำหรับแสดง
    div_text = ""
    if bullish_rsi_div:
        div_text += "📈 RSI Bull Div ✅ "
    if bearish_rsi_div:
        div_text += "📉 RSI Bear Div ✅ "
    if bullish_macd_div:
        div_text += "📈 MACD Bull Div ✅ "
    if bearish_macd_div:
        div_text += "📉 MACD Bear Div ✅ "
    if not div_text:
        div_text = "Div: ไม่พบ"

    # ตัดสินสัญญาณ ต้องได้ 4/6
    if long_score >= 4:
        status = "🟢 SPOT ซื้อจ้า V66"
        detail = f"Long {long_score}/6 [EMA{'✅' if ema_cross_up else '❌'} MACD{'✅' if macd_cross_up else '❌'} EMA200{'✅' if above_200 else '❌'} RSI{'✅' if rsi_long else '❌'} Div{'✅' if bullish_rsi_div or bullish_macd_div else '❌'}]"
    elif short_score >= 4:
        status = "🔴 SPOT ขายจ้า V66"
        detail = f"Short {short_score}/6 [EMA{'✅' if ema_cross_down else '❌'} MACD{'✅' if macd_cross_down else '❌'} EMA200{'✅' if below_200 else '❌'} RSI{'✅' if rsi_short else '❌'} Div{'✅' if bearish_rsi_div or bearish_macd_div else '❌'}]"
    else:
        status = "💎 รอก่อน / ถือไว้ V66"
        detail = f"Long {long_score}/6 Short {short_score}/6"

    msg = (
        f"V66 [{SYMBOL}] {status}\n"
        f"📅 {t}\n"
        f"💰 ราคา ${price:.2f} | {used_ex}\n"
        f"📊 BOLL {boll:.2f} | UB {ub:.2f} | LB {lb:.2f}\n"
        f"📈 EMA200 {ema200:.1f} | ATR {atr_v:.2f} | RSI {rsi_v:.1f}\n"
        f"🔍 {detail}\n"
        f"🌀 {div_text}\n"
        f"--------------------------------"
    )

    send_telegram(msg)
    return msg

def bot_loop():
    print("🚀 V66 Divergent Bot Started")
    time.sleep(10)
    while True:
        try:
            msg = run_v66_once()
            print(msg)
        except Exception as e:
            print(f"Loop error: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(3600)

def keep_alive_loop():
    print("Keep-Alive Started")
    time.sleep(20)
    while True:
        try:
            r = requests.get(BASE_URL, timeout=10)
            print(f"Keep-Alive / : {r.status_code}")
            r2 = requests.get(f"{BASE_URL}/ping", timeout=10)
            print(f"Keep-Alive /ping: {r2.status_code}")
        except Exception as e:
            print(f"Keep-Alive error: {e}")
        time.sleep(600)

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=keep_alive_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
