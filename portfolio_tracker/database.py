import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS apis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            api_key TEXT NOT NULL,
            secret_key TEXT NOT NULL,
            passphrase TEXT NOT NULL,
            account_type TEXT DEFAULT 'spot',
            commission_rate REAL DEFAULT 0.0,
            simulated INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id INTEGER REFERENCES apis(id),
            api_name TEXT,
            inst_id TEXT NOT NULL,
            side TEXT NOT NULL,
            pos_side TEXT NOT NULL,
            size REAL NOT NULL,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            pnl_percent REAL,
            commission_rate REAL DEFAULT 0,
            commission_charged REAL DEFAULT 0,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def add_api(name: str, api_key: str, secret_key: str, passphrase: str,
            account_type: str = "spot", commission_rate: float = 0.0, simulated: bool = False) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO apis (name, api_key, secret_key, passphrase, account_type, commission_rate, simulated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, api_key, secret_key, passphrase, account_type, commission_rate, int(simulated)),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def delete_api(api_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM apis WHERE id = ?", (api_id,))
    conn.execute("DELETE FROM trades WHERE api_id = ?", (api_id,))
    conn.commit()
    conn.close()


def get_all_apis() -> List[Dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM apis ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_api(api_id: int, **kwargs):
    allowed = {"name", "api_key", "secret_key", "passphrase", "account_type", "commission_rate", "simulated"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [api_id]
    conn = get_conn()
    conn.execute(f"UPDATE apis SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def add_trade(api_id: int, api_name: str, inst_id: str, side: str, pos_side: str,
              size: float, entry_price: float = None, commission_rate: float = 0) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO trades (api_id, api_name, inst_id, side, pos_side, size, entry_price, commission_rate, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')",
        (api_id, api_name, inst_id, side, pos_side, size, entry_price, commission_rate),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def close_trade(trade_id: int, exit_price: float, pnl: float, pnl_percent: float):
    conn = get_conn()
    row = conn.execute("SELECT commission_rate, pnl FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not row:
        conn.close()
        return
    rate = row["commission_rate"]
    commission = abs(pnl) * (rate / 100) if pnl > 0 else 0
    conn.execute(
        "UPDATE trades SET exit_price=?, pnl=?, pnl_percent=?, commission_charged=?, status='closed', closed_at=? WHERE id=?",
        (exit_price, pnl, pnl_percent, commission, datetime.now().isoformat(), trade_id),
    )
    conn.commit()
    conn.close()


def get_trades(api_id: Optional[int] = None, status: Optional[str] = None) -> List[Dict]:
    conn = get_conn()
    query = "SELECT * FROM trades"
    params = []
    conditions = []
    if api_id is not None:
        conditions.append("api_id = ?")
        params.append(api_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_dashboard_summary() -> Dict:
    conn = get_conn()
    apis = conn.execute("SELECT COUNT(*) as c FROM apis").fetchone()["c"]
    open_trades = conn.execute("SELECT COUNT(*) as c FROM trades WHERE status='open'").fetchone()["c"]
    total_pnl = conn.execute("SELECT COALESCE(SUM(pnl), 0) as s FROM trades WHERE status='closed'").fetchone()["s"]
    total_commission = conn.execute("SELECT COALESCE(SUM(commission_charged), 0) as s FROM trades WHERE status='closed'").fetchone()["s"]
    conn.close()
    return {
        "total_apis": apis,
        "open_trades": open_trades,
        "total_pnl": total_pnl,
        "total_commission": total_commission,
    }
