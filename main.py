from flask import Flask, render_template_string, request, jsonify
from bip_utils import Bip39SeedGenerator, Bip39MnemonicValidator, Bip44, Bip44Coins, Bip44Changes
from stellar_sdk import Keypair, Server, TransactionBuilder, Network, Asset
import threading, time

app = Flask(__name__)

# === Global Wallet State ===
w_state = {
    "mnemonic": None,
    "public": None,
    "secret": None,
    "destination": None,
    "amount": None,
    "memo": "",
    "auto_active": False,
    "last_tx_hash": None
}

HORIZON_URL = "https://api.mainnet.minepi.com"
NETWORK_PASSPHRASE = "Pi Mainnet"

# === Background Worker ===
def auto_loop():
    while True:
        if w_state["auto_active"] and w_state["secret"] and w_state["destination"] and w_state["amount"]:
            try:
                send_transaction()
            except Exception as e:
                print("[!] Auto-send error:", e)
        time.sleep(1)  # Real-time balance + send every 1s

def send_transaction():
    kp = Keypair.from_secret(w_state["secret"])
    server = Server(horizon_url=HORIZON_URL)
    source_account = server.load_account(kp.public_key)

    tx = TransactionBuilder(
        source_account=source_account,
        network_passphrase=NETWORK_PASSPHRASE,
        base_fee=100
    ).append_payment_op(
        destination=w_state["destination"],
        amount=w_state["amount"],
        asset=Asset.native()
    )

    if w_state["memo"]:
        tx.add_text_memo(w_state["memo"])

    tx = tx.build()
    tx.sign(kp)
    response = server.submit_transaction(tx)
    w_state["last_tx_hash"] = response['hash']

@app.route("/")
def index():
    return render_template_string(TEMPLATE_HTML, wallet=w_state)

@app.route("/load", methods=["POST"])
def load_wallet():
    mnemonic = request.form.get("mnemonic").strip()
    if not Bip39MnemonicValidator().IsValid(mnemonic):
        return jsonify({"status": "error", "msg": "Invalid mnemonic."})

    seed = Bip39SeedGenerator(mnemonic).Generate()
    acc = Bip44.FromSeed(seed, Bip44Coins.STELLAR).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
    kp = Keypair.from_secret(acc.PrivateKey().ToWif())
    w_state["mnemonic"] = mnemonic
    w_state["public"] = kp.public_key
    w_state["secret"] = kp.secret
    return jsonify({"status": "ok", "public": kp.public_key})

@app.route("/balance")
def balance():
    try:
        server = Server(horizon_url=HORIZON_URL)
        acc = server.accounts().account_id(w_state["public"]).call()
        return jsonify({"balances": acc["balances"]})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/txs")
def txs():
    try:
        server = Server(horizon_url=HORIZON_URL)
        records = server.transactions().for_account(w_state["public"]).limit(5).order(desc=True).call()
        return jsonify({"txs": records["_embedded"]["records"]})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/config", methods=["POST"])
def config():
    w_state["destination"] = request.form.get("destination").strip()
    w_state["amount"] = request.form.get("amount").strip()
    w_state["memo"] = request.form.get("memo", "").strip()
    return jsonify({"status": "ok"})

@app.route("/toggle")
def toggle():
    w_state["auto_active"] = not w_state["auto_active"]
    return jsonify({"auto_active": w_state["auto_active"]})

TEMPLATE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Pi Wallet Web</title>
    <script>
        async function loadWallet() {
            const res = await fetch('/load', {
                method: 'POST',
                body: new FormData(document.getElementById('walletForm'))
            });
            const data = await res.json();
            alert(data.msg || "Wallet Loaded: " + data.public);
        }

        async function updateBalance() {
            const res = await fetch('/balance');
            const data = await res.json();
            let out = "";
            (data.balances || []).forEach(b => {
                out += `${b.balance} ${b.asset_type}<br>`;
            });
            document.getElementById('balance').innerHTML = out;
        }

        async function updateTxs() {
            const res = await fetch('/txs');
            const data = await res.json();
            let out = "";
            (data.txs || []).forEach(t => {
                out += `Hash: ${t.hash}<br>Memo: ${t.memo || ""}<br><hr>`;
            });
            document.getElementById('txs').innerHTML = out;
        }

        async function toggleLoop() {
            const res = await fetch('/toggle');
            const data = await res.json();
            document.getElementById('loopBtn').innerText = data.auto_active ? 'Stop Auto' : 'Start Auto';
        }

        async function updateConfig() {
            const form = new FormData(document.getElementById('sendForm'));
            const res = await fetch('/config', { method: 'POST', body: form });
        }

        setInterval(() => {
            updateBalance();
            updateTxs();
        }, 1000);
    </script>
</head>
<body>
    <h2>Pi Wallet Web</h2>
    <form id="walletForm">
        <textarea name="mnemonic" rows="3" cols="60">Enter your 24-word mnemonic here...</textarea><br>
        <button type="button" onclick="loadWallet()">Load Wallet</button>
    </form>

    <h3>Public Address:</h3>
    <div>{{ wallet.public }}</div>

    <h3>Balance:</h3>
    <div id="balance">Loading...</div>

    <h3>Send Pi</h3>
    <form id="sendForm">
        To: <input name="destination" size="60"><br>
        Amount: <input name="amount"><br>
        Memo: <input name="memo"><br>
        <button type="button" onclick="updateConfig()">Save Send Info</button>
    </form>

    <button id="loopBtn" onclick="toggleLoop()">Start Auto</button>

    <h3>Recent Transactions</h3>
    <div id="txs">Loading...</div>
</body>
</html>
"""

# Start background thread
t = threading.Thread(target=auto_loop, daemon=True)
t.start()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
