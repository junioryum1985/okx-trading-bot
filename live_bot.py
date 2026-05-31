#!/usr/bin/env python3
"""
Live Trading Bot - BTC-USD-SWAP Perpetual Futures
Estratégia: MA_Crossover (EMA 9/21) | Timeframe: 1D
Leverage: 5x | TP: 6% | SL: 9%
Lê credenciais do config.yaml
"""

import os, sys, time, threading
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portfolio_tracker.config import load_config
from portfolio_tracker.trader import execute_trade, Trader
from portfolio_tracker.client import OKXClient
from backtest import ema, fetch_data

INSTRUMENTO = "BTC-USD-SWAP"
TIMEFRAME = "1D"
LEVERAGE = 5
TP_PCT = 6.0
SL_PCT = 9.0
CHECK_INTERVAL = 3600
CAPITAL_PCT = 0.95


def get_balance_usd(api: dict) -> float:
    client = OKXClient(api["api_key"], api["secret_key"],
                       api["passphrase"], api.get("simulated", False))
    try:
        balances = client.get_balance()
        for b in balances:
            eq = b.get("usd_eq", 0)
            if b["currency"] in ("USDT", "USD", "BTC") and eq > 0:
                ratio = b["available"] / b["equity"] if b.get("equity", 0) > 0 else 0
                return ratio * eq * CAPITAL_PCT
        return 50.0
    except Exception:
        return 50.0


def get_position(trader: Trader) -> dict:
    positions = trader.get_positions(inst_type="SWAP")
    for pos in positions:
        if pos["instId"] == INSTRUMENTO:
            return pos
    return {}


def check_signal(data: list) -> int:
    closes = [d["c"] for d in data]
    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)
    curr = len(data) - 1
    prev = curr - 1

    if ema_fast[prev] <= ema_slow[prev] and ema_fast[curr] > ema_slow[curr]:
        return 1
    if ema_fast[prev] >= ema_slow[prev] and ema_fast[curr] < ema_slow[curr]:
        return -1
    return 0


LOG = []

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG.append(line)
    if len(LOG) > 200:
        LOG[:] = LOG[-100:]


def run_bot(api: dict):
    trader = Trader(api["api_key"], api["secret_key"],
                    api["passphrase"], api.get("simulated", False))
    last_ts = 0

    log(f"Conectado: {api['name']} | Simulado: {api.get('simulated', False)}")
    log(f"Monitorando {INSTRUMENTO} em {TIMEFRAME}\n")

    while True:
        try:
            data = fetch_data(INSTRUMENTO, TIMEFRAME, 100)
            if len(data) < 50:
                log(f"Dados insuficientes ({len(data)})")
                time.sleep(60)
                continue

            latest = data[-1]
            if latest["ts"] == last_ts:
                time.sleep(CHECK_INTERVAL)
                continue

            price = latest["c"]
            signal = check_signal(data)

            if signal != 0:
                direction = "long" if signal == 1 else "short"
                pos = get_position(trader)

                if pos:
                    pos_side = pos.get("posSide", "")
                    if (direction == "long" and pos_side == "long") or \
                       (direction == "short" and pos_side == "short"):
                        log(f"SINAL {direction.upper()} (já posicionado)")
                        last_ts = latest["ts"]
                        time.sleep(CHECK_INTERVAL)
                        continue
                    log(f"Invertendo posição para {direction.upper()}...")
                    trader.close_position(INSTRUMENTO)
                    time.sleep(1)

                entry_amount = get_balance_usd(api)
                tp_price = price * (1 + TP_PCT / 100) if direction == "long" else price * (1 - TP_PCT / 100)
                sl_price = price * (1 - SL_PCT / 100) if direction == "long" else price * (1 + SL_PCT / 100)

                log(f"SINAL {direction.upper()} | Entry: ${price:,.2f} | "
                    f"TP: ${tp_price:,.2f} | SL: ${sl_price:,.2f} | Capital: ${entry_amount:.2f}")

                result = execute_trade(api, INSTRUMENTO, direction, entry_amount,
                                       leverage=LEVERAGE, tp_price=tp_price,
                                       sl_price=sl_price, td_mode="inverse")

                if result.get("success"):
                    log(f"✅ Ordem OK | ID: {result['order_id']} | Preço: ${result['entry_price']:,.2f}")
                else:
                    log(f"❌ Erro: {result.get('error')}")
            else:
                closes = [d["c"] for d in data]
                ef = ema(closes, 9)[-1]
                es = ema(closes, 21)[-1]
                log(f"BTC: ${price:,.2f} | EMA9: ${ef:,.2f} | EMA21: ${es:,.2f} | Aguardando sinal")

            last_ts = latest["ts"]
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            log(f"ERRO: {e}")
            time.sleep(60)


# ═══════════════════════════════════════════════════════════════════════
#  HEALTH CHECK (obrigatório para Render Web Service)
# ═══════════════════════════════════════════════════════════════════════

def health_server():
    import http.server
    import json

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                status = {"status": "running", "logs": LOG[-10:]}
                self.wfile.write(json.dumps(status).encode())
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, *a):
            pass

    port = int(os.environ.get("PORT", 8080))
    server = http.server.HTTPServer(("0.0.0.0", port), H)
    log(f"Health check server na porta {port}")
    server.serve_forever()


def main():
    print("=" * 60)
    print("  LIVE TRADING BOT - BTC PERPETUAL FUTURES")
    print(f"  Estratégia: MA_Crossover | {TIMEFRAME} | {LEVERAGE}x")
    print(f"  TP: {TP_PCT}% | SL: {SL_PCT}%")
    print("=" * 60)

    wallets = load_config()
    if not wallets:
        log("Nenhuma wallet no config.yaml")
        return

    api = wallets[0]
    print(f"\n  Wallet: {api['name']}")
    print(f"  Modo: {'DEMO' if api.get('simulated') else 'REAL'}")
    if not api.get("simulated"):
        print("  ⚠ ATENÇÃO: Modo REAL!")
        for i in range(5, 0, -1):
            print(f"  Iniciando em {i}...", end="\r")
            time.sleep(1)

    threading.Thread(target=run_bot, args=(api,), daemon=True).start()
    health_server()


if __name__ == "__main__":
    main()
