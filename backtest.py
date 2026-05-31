#!/usr/bin/env python3
"""
Backtest BTC-USD-SWAP Perpetual Futures - OKX
Testa 3 estratégias com variações de timeframe, TP, SL e alavancagem.
"""

import os, sys, time, sqlite3, math, json
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from okx.api.market import Market

INSTRUMENTO = "BTC-USD-SWAP"
CAPITAL_INICIAL = 1000.0
CACHE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ohlcv_cache.db")

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1H", "4H", "1D"]
LEVERAGES = [1, 2, 3, 4, 5]
TPS = list(range(1, 11))
SLS = list(range(1, 11))


# ═══════════════════════════════════════════════════════════════════════
#  DATA FETCHING & CACHING
# ═══════════════════════════════════════════════════════════════════════

def _get_conn():
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS ohlcv (
        inst_id TEXT, tf TEXT, ts INTEGER,
        o REAL, h REAL, l REAL, c REAL, vol REAL,
        PRIMARY KEY (inst_id, tf, ts)
    )""")
    return conn

def fetch_data(inst_id: str, tf: str, max_candles: int) -> List[Dict]:
    conn = _get_conn()
    cached = conn.execute(
        "SELECT ts, o, h, l, c, vol FROM ohlcv WHERE inst_id=? AND tf=? ORDER BY ts ASC",
        (inst_id, tf)
    ).fetchall()

    if len(cached) >= max_candles:
        conn.close()
        return [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "vol": r[5]} for r in cached]

    market = Market(flag="0")
    all_data = []
    after = ""
    print(f"  Baixando dados {tf}...")

    while len(all_data) < max_candles:
        params = {"instId": inst_id, "bar": tf, "limit": "100"}
        if after:
            params["after"] = str(after)

        try:
            result = market.get_history_candles(**params)
        except Exception as e:
            print(f"  [ERRO] {e}")
            break

        if result.get("code") != "0":
            print(f"  [ERRO] {result.get('msg')}")
            break

        batch = result.get("data", [])
        if not batch:
            break

        for c in batch:
            ts = int(c[0])
            all_data.append({
                "ts": ts, "o": float(c[1]), "h": float(c[2]),
                "l": float(c[3]), "c": float(c[4]), "vol": float(c[5]),
            })

        after = batch[-1][0]
        if len(batch) < 100:
            break
        time.sleep(0.2)

    print(f"  Obtidos {len(all_data)} candles")

    if all_data:
        conn.executemany(
            "INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?,?)",
            [(inst_id, tf, d["ts"], d["o"], d["h"], d["l"], d["c"], d["vol"]) for d in all_data]
        )
        conn.commit()

    conn.close()
    all_data.sort(key=lambda d: d["ts"])
    return all_data


# ═══════════════════════════════════════════════════════════════════════
#  INDICATORS
# ═══════════════════════════════════════════════════════════════════════

def ema(data: List[float], period: int) -> List[float]:
    result = [0.0] * len(data)
    multiplier = 2.0 / (period + 1)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = (data[i] - result[i-1]) * multiplier + result[i-1]
    return result

def rsi(data: List[float], period: int = 14) -> List[float]:
    if len(data) < period + 1:
        return [50.0] * len(data)
    result = [50.0] * period
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = data[i] - data[i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
    result.append(100.0 - 100.0 / (1.0 + rs))
    for i in range(period + 1, len(data)):
        diff = data[i] - data[i-1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
        result.append(100.0 - 100.0 / (1.0 + rs))
    return result

def bb(data: List[float], period: int = 20, std_dev: float = 2.0):
    result = {"upper": [0.0]*len(data), "mid": [0.0]*len(data), "lower": [0.0]*len(data)}
    for i in range(period - 1, len(data)):
        window = data[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        result["mid"][i] = mean
        result["upper"][i] = mean + std_dev * std
        result["lower"][i] = mean - std_dev * std
    return result


# ═══════════════════════════════════════════════════════════════════════
#  STRATEGIES - return list of signals (1=long, -1=short, 0=neutral)
# ═══════════════════════════════════════════════════════════════════════

def strategy_ma_crossover(data: List[Dict]) -> List[int]:
    closes = [d["c"] for d in data]
    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)
    signals = [0] * len(data)
    for i in range(1, len(data)):
        if ema_fast[i-1] <= ema_slow[i-1] and ema_fast[i] > ema_slow[i]:
            signals[i] = 1
        elif ema_fast[i-1] >= ema_slow[i-1] and ema_fast[i] < ema_slow[i]:
            signals[i] = -1
    return signals

def strategy_rsi(data: List[Dict]) -> List[int]:
    closes = [d["c"] for d in data]
    rsi_vals = rsi(closes, 14)
    oversold, overbought = 30, 70
    signals = [0] * len(data)
    for i in range(1, len(data)):
        if rsi_vals[i-1] <= oversold and rsi_vals[i] > oversold:
            signals[i] = 1
        elif rsi_vals[i-1] >= overbought and rsi_vals[i] < overbought:
            signals[i] = -1
    return signals

def strategy_bb(data: List[Dict]) -> List[int]:
    closes = [d["c"] for d in data]
    bb_vals = bb(closes, 20, 2.0)
    signals = [0] * len(data)
    for i in range(1, len(data)):
        low = data[i]["l"]
        high = data[i]["h"]
        upper = bb_vals["upper"][i]
        lower = bb_vals["lower"][i]
        if low <= lower and closes[i] > data[i]["o"]:
            signals[i] = 1
        elif high >= upper and closes[i] < data[i]["o"]:
            signals[i] = -1
    return signals


STRATEGIES = {
    "MA_Crossover": strategy_ma_crossover,
    "RSI": strategy_rsi,
    "Bollinger": strategy_bb,
}


# ═══════════════════════════════════════════════════════════════════════
#  BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TradeResult:
    entry_ts: int
    exit_ts: int
    side: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_usd: float
    reason: str

@dataclass  
class BacktestResult:
    strategy: str
    timeframe: str
    leverage: int
    tp_pct: int
    sl_pct: int
    total_return: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    max_drawdown: float
    sharpe: float
    avg_return: float
    trades_details: List = None

def run_backtest(data: List[Dict], signals: List[int],
                 leverage: int, tp_pct: int, sl_pct: int) -> BacktestResult:
    balance = CAPITAL_INICIAL
    peak = CAPITAL_INICIAL
    max_dd = 0.0
    trades = []
    in_position = False
    entry_price = 0.0
    entry_ts = 0
    side = ""
    returns = []

    tp_mult = 1.0 + tp_pct / 100.0
    sl_mult = 1.0 - sl_pct / 100.0

    for i in range(len(data)):
        c = data[i]
        price = c["c"]

        if in_position:
            hit_tp = False
            hit_sl = False
            if side == "long":
                if c["h"] >= entry_price * tp_mult:
                    hit_tp = True
                    exit_price = entry_price * tp_mult
                elif c["l"] <= entry_price * sl_mult:
                    hit_sl = True
                    exit_price = entry_price * sl_mult
            else:
                if c["l"] <= entry_price / tp_mult:
                    hit_tp = True
                    exit_price = entry_price / tp_mult
                elif c["h"] >= entry_price / sl_mult:
                    hit_sl = True
                    exit_price = entry_price / sl_mult

            if hit_tp or hit_sl:
                price_move = (exit_price - entry_price) / entry_price
                if side == "short":
                    price_move = -price_move
                r = price_move * leverage
                pnl = balance * r
                balance += pnl
                returns.append(r)
                reason = "TP" if hit_tp else "SL"
                trades.append(TradeResult(entry_ts, c["ts"], side, entry_price, exit_price, r * 100, pnl, reason))
                in_position = False
                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        else:
            sig = signals[i]
            if sig != 0 and i > 0:
                in_position = True
                entry_price = price
                entry_ts = c["ts"]
                side = "long" if sig == 1 else "short"

    if in_position:
        exit_price = data[-1]["c"]
        price_move = (exit_price - entry_price) / entry_price
        if side == "short":
            price_move = -price_move
        r = price_move * leverage
        pnl = balance * r
        balance += pnl
        returns.append(r)
        trades.append(TradeResult(entry_ts, data[-1]["ts"], side, entry_price, exit_price, r * 100, pnl, "final"))

    total_return = (balance - CAPITAL_INICIAL) / CAPITAL_INICIAL * 100
    wins = sum(1 for t in trades if t.pnl_usd > 0)
    losses = sum(1 for t in trades if t.pnl_usd <= 0)
    win_rate = (wins / len(trades) * 100) if trades else 0
    avg_ret = (sum(r for r in returns) / len(returns) * 100) if returns else 0
    sharpe = (sum(returns) / len(returns) / max(max_safe := math.sqrt(
        sum((r - sum(returns)/len(returns))**2 for r in returns) / len(returns)
    ) or 0.0001, 0.0001)) * math.sqrt(len(returns)) if len(returns) > 1 else 0

    return BacktestResult(
        strategy="", timeframe="", leverage=leverage,
        tp_pct=tp_pct, sl_pct=sl_pct,
        total_return=total_return, total_trades=len(trades),
        wins=wins, losses=losses, win_rate=win_rate,
        max_drawdown=max_dd, sharpe=sharpe, avg_return=avg_ret,
        trades_details=trades,
    )


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  BACKTEST BTC-USD-SWAP PERPETUAL FUTURES")
    print("  Estratégias: MA Crossover | RSI | Bollinger Bands")
    print(f"  Período: 1 ano | Capital: ${CAPITAL_INICIAL:.2f}")
    print("=" * 70)

    candles_per_tf = {"1m": 10000, "5m": 8000, "15m": 6000,
                      "30m": 4000, "1H": 3000, "4H": 1000, "1D": 400}

    results = []

    for tf in TIMEFRAMES:
        print(f"\n{'─'*50}")
        print(f"TIMEFRAME: {tf}")
        print(f"{'─'*50}")

        data = fetch_data(INSTRUMENTO, tf, candles_per_tf[tf])
        if len(data) < 50:
            print(f"  Dados insuficientes ({len(data)} candles), pulando...")
            continue

        first_ts = datetime.fromtimestamp(data[0]["ts"] / 1000, tz=timezone.utc)
        last_ts = datetime.fromtimestamp(data[-1]["ts"] / 1000, tz=timezone.utc)
        days = (last_ts - first_ts).days
        print(f"  Período: {first_ts.date()} a {last_ts.date()} ({days} dias)")
        print(f"  Candles: {len(data)}")

        for strat_name, strat_func in STRATEGIES.items():
            print(f"\n  ▶ Estratégia: {strat_name}")
            t0 = time.time()
            signals = strat_func(data)
            total_sigs = sum(1 for s in signals if s != 0)
            long_sigs = sum(1 for s in signals if s == 1)
            short_sigs = sum(1 for s in signals if s == -1)
            print(f"    Sinais: {total_sigs} (LONG: {long_sigs}, SHORT: {short_sigs})")

            best = None
            worst = None

            for lev in LEVERAGES:
                for tp in TPS:
                    for sl in SLS:
                        r = run_backtest(data, signals, lev, tp, sl)
                        r_strat = strat_name
                        r.timeframe = tf
                        r.strategy = strat_name
                        results.append(r)

                        if best is None or r.total_return > best.total_return:
                            best = r
                        if worst is None or r.total_return < worst.total_return:
                            worst = r

            elapsed = time.time() - t0
            print(f"    Testados {len(LEVERAGES) * len(TPS) * len(SLS)} combos em {elapsed:.1f}s")
            if best:
                print(f"    ✓ Melhor: +{best.total_return:.2f}% | Lev {best.leverage}x TP {best.tp_pct}% SL {best.sl_pct}%")
            if worst:
                print(f"    ✗ Pior: {worst.total_return:.2f}%")

    print(f"\n{'='*70}")
    print("  RESULTADOS GLOBAIS")
    print(f"{'='*70}")

    if not results:
        print("  Nenhum resultado. Verifique conexão com a internet.")
        return

    results.sort(key=lambda r: r.total_return, reverse=True)

    print(f"\n{'─'*110}")
    header = f"{'#':<3} {'Estratégia':<14} {'TF':<5} {'Lev':<4} {'TP%':<5} {'SL%':<5} {'Retorno%':<10} {'Trades':<7} {'Win%':<7} {'Drawdown':<10} {'Sharpe':<8}"
    print(header)
    print(f"{'─'*110}")

    top_n = 20
    for rank, r in enumerate(results[:top_n], 1):
        print(f"{rank:<3} {r.strategy:<14} {r.timeframe:<5} {r.leverage}x  {r.tp_pct:<4} {r.sl_pct:<5} "
              f"{r.total_return:>+8.2f}%  {r.total_trades:<5}  {r.win_rate:>5.1f}%  "
              f"{r.max_drawdown:>7.2f}%  {r.sharpe:>+7.2f}")

    print(f"\n{'─'*110}")

    best = results[0]
    print(f"\n🏆  MELHOR ESTRATÉGIA:")
    print(f"   Estratégia : {best.strategy}")
    print(f"   Timeframe  : {best.timeframe}")
    print(f"   Alavancagem: {best.leverage}x")
    print(f"   Take Profit: {best.tp_pct}%")
    print(f"   Stop Loss  : {best.sl_pct}%")
    print(f"   Retorno    : +{best.total_return:.2f}% (${CAPITAL_INICIAL * (1 + best.total_return/100):.2f})")
    print(f"   Trades     : {best.total_trades}")
    print(f"   Win Rate   : {best.win_rate:.1f}%")
    print(f"   Max DD     : {best.max_drawdown:.2f}%")
    print(f"   Sharpe     : {best.sharpe:.2f}")

    print(f"\n📋  TOP 5 COMBINAÇÕES:")
    for i, r in enumerate(results[:5], 1):
        print(f"   {i}. {r.strategy} | {r.timeframe} | {r.leverage}x | TP {r.tp_pct}% SL {r.sl_pct}% → "
              f"{r.total_return:>+7.2f}% (Win: {r.win_rate:.0f}%, DD: {r.max_drawdown:.1f}%)")

    with open("backtest_results.json", "w") as f:
        json.dump([{
            "strategy": r.strategy, "timeframe": r.timeframe,
            "leverage": r.leverage, "tp_pct": r.tp_pct, "sl_pct": r.sl_pct,
            "total_return": round(r.total_return, 2),
            "total_trades": r.total_trades, "win_rate": round(r.win_rate, 1),
            "max_drawdown": round(r.max_drawdown, 2), "sharpe": round(r.sharpe, 2),
        } for r in results], f, indent=2)
    print(f"\nResultados salvos em backtest_results.json")


if __name__ == "__main__":
    main()
