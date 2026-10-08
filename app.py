import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <h1>V65 Binance Bot LIVE ✅</h1>
    <p>PAXG/USDT - 08/10/2026 20:19 - Status: LIVE</p>
    <p>Render Free Instance Running OK</p>
    <p><a href="/check">/check - Test Trading</a></p>
    <p>Bot will send Telegram every hour</p>
    """, 200

@app.route("/check")
def check():
    return """
    <h1>Bot Check OK</h1>
    <p>Flask is LIVE. Ready to add ccxt/pandas-ta after confirmed LIVE.</p>
    <p>Next step: Add trading libs to requirements.txt</p>
    """, 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting V65 ULTIMATE on port {port}")
    app.run(host="0.0.0.0", port=port)
