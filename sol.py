import json
import time
import threading
import requests
import websocket
import os

# =========================
# CONFIG (ENV ONLY)
# =========================
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
WATCH_ADDRESS = os.getenv("WATCH_SOLANA_ADDRESS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SOL_THRESHOLD = 10_000

if not all([HELIUS_API_KEY, WATCH_ADDRESS, TELEGRAM_TOKEN]):
    raise Exception("ENV variables not set")

RPC_HTTP = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_TX_API = f"https://api-mainnet.helius-rpc.com/v0/transactions?api-key={HELIUS_API_KEY}"
WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# =========================
# TELEGRAM AUTO CHAT ID
# =========================
def get_chat_id():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    r = requests.get(url).json()

    if not r.get("result"):
        raise Exception("No Telegram messages found. Send /start to the bot first.")

    return r["result"][-1]["message"]["chat"]["id"]

CHAT_ID = get_chat_id()
print(f"Telegram chat_id detected: {CHAT_ID}")

# =========================
# TELEGRAM SEND
# =========================
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }
    requests.post(url, data=payload)

# =========================
# SOL BALANCE
# =========================
def get_sol_balance(address):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [address]
    }
    r = requests.post(RPC_HTTP, json=payload).json()
    lamports = r.get("result", {}).get("value", 0)
    return lamports / 1_000_000_000

# =========================
# TRANSACTION PARSER
# =========================
def parse_transaction(signature):
    try:
        r = requests.post(
            HELIUS_TX_API,
            json={"transactions": [signature]}
        ).json()

        if not r or not isinstance(r, list):
            return

        tx = r[0]
        transfers = tx.get("tokenTransfers", [])
        if not transfers:
            return

        for t in transfers:
            if t.get("toUserAccount") != WATCH_ADDRESS:
                continue

            mint = t.get("mint")
            creator = tx.get("feePayer")

            sol_balance = get_sol_balance(creator)
            status = "✅" if sol_balance >= SOL_THRESHOLD else "❌"

            msg = (
                f"{status} New SPL token received\n\n"
                f"Mint:\n{mint}\n\n"
                f"Creator:\n{creator}\n\n"
                f"SOL balance: {sol_balance:.2f} SOL\n\n"
                f"https://solscan.io/account/{creator}"
            )

            send_telegram(msg)

    except Exception as e:
        print("Parse error:", e)

# =========================
# WEBSOCKET HANDLERS
# =========================
def on_message(ws, message):
    data = json.loads(message)

    if data.get("method") != "logsNotification":
        return

    signature = data["params"]["result"]["value"].get("signature")

    threading.Thread(
        target=parse_transaction,
        args=(signature,),
        daemon=True
    ).start()

def on_open(ws):
    sub = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "logsSubscribe",
        "params": [
            {"mentions": [WATCH_ADDRESS]},
            {"commitment": "confirmed"}
        ]
    }
    ws.send(json.dumps(sub))
    print(f"Subscribed to {WATCH_ADDRESS}")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message
    )

    while True:
        try:
            ws.run_forever()
        except Exception as e:
            print("WebSocket error, reconnecting...", e)
            time.sleep(5)
