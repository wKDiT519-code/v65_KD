import ccxt
import pandas as pd
import pandas_ta as ta
from datetime import datetime
import pytz
import time
import os
import threading
from flask import Flask

SYMBOL = "PAXG/USDT"
TIMEFRAME = "1h"
EMA_FAST, EMA_SLOW, EMA_TREND = 12, 26, 200
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
RSI_PERIOD, BB_PERIOD, BB_STD, ATR_PERIOD = 14, 20, 2.0, 14
MAX_SL_PCT, MIN_SL_PCT = 0.06, 0.008
THAI_TZ = pytz.timezone('Asia/Bangkok')
TRADE_MODE = "SPOT"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

app = Flask(__name__)

@app.route("/")
def health():
    return f"V65 Binance Bot Running OK - {datetime.now(THAI_TZ).strftime('%d/%m/%Y %H:%M')} - PAXG/USDT 1H", 200

@app.route("/check")
def manual_check():
    try:
        msg = run_hourly_check()
        return f"<pre>{msg}</pre>", 200
    except Exception as e:
        return f"Error: {e}", 500

def send_telegram_auto(msg):
    import requests
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(msg)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def thai_time_now():
    return datetime.now(THAI_TZ).strftime("%d/%m/%Y %H:%M น. เวลาไทย")

def tg_message(state, price, info, balance=None, pnl=None, boll_info=""):
    t = thai_time_now()
    base = f"V65_binance [{SYMBOL} Binance] {state}\n📅 {t}\nราคา Binance ${price:.2f} {boll_info}\n{info}"
    if balance is not None:
        base += f"\n💰 คงเหลือ ${balance:.2f} | PnL {pnl}"
    return base

def highlight_buy():
    return "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n🟢🟢 <b>➡ SPOT ซื้อจ้า</b> 🟢🟢\n🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩"
def highlight_sell():
    return "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n🔴🔴 <b>➡ SPOT ขายจ้า</b> 🔴🔴\n🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥"
def highlight_hold():
    return "🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦\n💎💎 <b>✊ ถือไว้/รอก่อน</b> 💎💎\n🟨🟨 <b>⏳ รอสัญญาณชัดๆ</b> 🟨🟨\n🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦"
def highlight_wait():
    return "🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨\n⏳⏳ <b>รอก่อน... ยังไม่เข้าเกณฑ์</b> ⏳⏳\n🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨"

def is_news_time():
    from datetime import timedelta
    now = datetime.now(THAI_TZ)
    first_day = now.replace(day=1)
    days_ahead = (4 - first_day.weekday()) % 7
    first_friday = first_day + timedelta(days=days_ahead)
    if now.day == first_friday.day and now.weekday() == 4:
        if 18 <= now.hour <= 21:
            if now.hour == 18 and now.minute >= 30: return True, f"NFP วันนี้ {now.strftime('%d/%m')} 19:30 น."
            if now.hour in [19,20]: return True, f"NFP วันนี้ {now.strftime('%d/%m')} 19:30 น."
            if now.hour == 21 and now.minute <= 30: return True, f"NFP วันนี้ {now.strftime('%d/%m')} 19:30 น."
    return False, ""
def is_funding_time():
    now = datetime.now(THAI_TZ)
    if TRADE_MODE == "SPOT": return False, ""
    return False, ""
def is_high_volatility(df):
    if df is None or len(df) < 30: return False, ""
    atr = df['ATR'].iloc[-1]
    atr_avg = df['ATR'].tail(20).mean()
    if atr > atr_avg * 2.5: return True, f"ทองกระชาก ATR {atr:.2f}"
    return False, ""
def check_divergence(df):
    recent = df.tail(20)
    bullish_div = recent['close'].iloc[-1] < recent['close'].iloc[-10] and recent['RSI'].iloc[-1] > recent['RSI'].iloc[-10]
    bearish_div = recent['close'].iloc[-1] > recent['close'].iloc[-10] and recent['RSI'].iloc[-1] < recent['RSI'].iloc[-10]
    return bullish_div, bearish_div
def calc_sl_dynamic(price, df, side="LONG"):
    atr = df['ATR'].iloc[-1]
    ema200 = df[f'EMA_{EMA_TREND}'].iloc[-1]
    lb, ub = df['LB'].iloc[-1], df['UB'].iloc[-1]
    recent_low, recent_high = df['low'].tail(20).min(), df['high'].tail(20).max()
    if side == "LONG":
        sl_atr = price - (atr * 1.8)
        sl_swing = recent_low - (atr * 0.3)
        sl_ema = ema200 * 0.995
        sl_boll = lb * 0.998
        candidates = [s for s in [sl_atr, sl_swing, sl_ema, sl_boll] if s < price]
        sl = max(candidates) if candidates else sl_atr
        sl = max(sl, price * (1-MAX_SL_PCT))
        sl = min(sl, price * (1-MIN_SL_PCT))
        return sl, atr, ""
    else:
        sl_atr = price + (atr * 1.8)
        sl_swing = recent_high + (atr * 0.3)
        sl_ema = ema200 * 1.005
        sl_boll = ub * 1.002
        candidates = [s for s in [sl_atr, sl_swing, sl_ema, sl_boll] if s > price]
        sl = min(candidates) if candidates else sl_atr
        sl = min(sl, price * (1+MAX_SL_PCT))
        sl = max(sl, price * (1+MIN_SL_PCT))
        return sl, atr, ""

def analyze(df, balance=1000, mode=TRADE_MODE):
    last = df.iloc[-1]
    price, ema12, ema26, ema200 = last['close'], last[f'EMA_{EMA_FAST}'], last[f'EMA_{EMA_SLOW}'], last[f'EMA_{EMA_TREND}']
    macd_dif, macd_dea, rsi, boll, ub, lb, atr = last['MACD'], last['MACD_S'], last['RSI'], last['BOLL'], last['UB'], last['LB'], last['ATR']
    bullish_div, bearish_div = check_divergence(df)
    funding, _ = is_funding_time()
    if funding: return tg_message("💸 Funding", price, "งดถือข้าม", boll_info=f"BOLL {boll:.2f}")
    news, news_name = is_news_time()
    if news: return tg_message("🔒 ปิดระบบข่าว NFP", price, f"มีข่าว {news_name}", boll_info=f"BOLL {boll:.2f}")
    vol, vol_msg = is_high_volatility(df)
    if vol: return tg_message("⚠️ ทองกระชาก", price, vol_msg, boll_info=f"BOLL {boll:.2f}")
    ema_cross_up = ema12 > ema26 and df[f'EMA_{EMA_FAST}'].iloc[-2] <= df[f'EMA_{EMA_SLOW}'].iloc[-2]
    macd_cross_up = macd_dif > macd_dea and df['MACD'].iloc[-2] <= df['MACD_S'].iloc[-2]
    above_ema200 = price > ema200
    rsi_ok_long = rsi > 45
    long_score = sum([ema_cross_up, macd_cross_up, above_ema200, rsi_ok_long or bullish_div])
    ema_cross_down = ema12 < ema26 and df[f'EMA_{EMA_FAST}'].iloc[-2] >= df[f'EMA_{EMA_SLOW}'].iloc[-2]
    macd_cross_down = macd_dif < macd_dea and df['MACD'].iloc[-2] >= df['MACD_S'].iloc[-2]
    below_ema200 = price < ema200
    rsi_ok_short = rsi < 55
    short_score = sum([ema_cross_down, macd_cross_down, below_ema200, rsi_ok_short or bearish_div])
    boll_info = f"BOLL {boll:.2f} UB {ub:.2f} LB {lb:.2f} EMA200 {ema200:.1f} ATR {atr:.2f}"
    if mode == "SPOT":
        if long_score >= 3:
            return tg_message("🟢 SPOT ซื้อจ้า", price, highlight_buy(), balance, "ซื้อสะสม", boll_info)
        if short_score >= 3:
            return tg_message("🔴 SPOT ขายจ้า", price, highlight_sell(), balance, "ขายทำกำไร", boll_info)
        hold_info = highlight_hold() + f"\nLong {long_score}/4 Short {short_score}/4 RSI {rsi:.1f} ATR {atr:.2f}"
        return tg_message("💎 ถือไว้/รอก่อน", price, hold_info, balance, "รอ", boll_info)
    return tg_message("⏳ รอก่อน", price, highlight_wait(), balance, "รอ", boll_info)

def fetch_chart():
    ex = ccxt.binance()
    ohlcv = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)
    df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
    df[f'EMA_{EMA_FAST}'] = ta.ema(df['close'], EMA_FAST)
    df[f'EMA_{EMA_SLOW}'] = ta.ema(df['close'], EMA_SLOW)
    df[f'EMA_{EMA_TREND}'] = ta.ema(df['close'], EMA_TREND)
    macd = ta.macd(df['close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    df = pd.concat([df, macd], axis=1)
    df['RSI'] = ta.rsi(df['close'], RSI_PERIOD)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], ATR_PERIOD)
    bb = ta.bbands(df['close'], length=BB_PERIOD, std=BB_STD)
    df['BOLL'] = bb[f'BBM_{BB_PERIOD}_{BB_STD}']
    df['UB'] = bb[f'BBU_{BB_PERIOD}_{BB_STD}']
    df['LB'] = bb[f'BBL_{BB_PERIOD}_{BB_STD}']
    return df

def run_hourly_check(balance=1000):
    df = fetch_chart()
    msg = analyze(df, balance=balance, mode=TRADE_MODE)
    send_telegram_auto(msg)
    return msg

def bot_loop():
    print("🚀 V65 Bot Loop Started")
    while True:
        try:
            print(run_hourly_check())
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(3600)

if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
