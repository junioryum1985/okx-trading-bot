from okx.api.account import Account
from okx.api.fundingaccount import FundingAccount
from okx.api.market import Market
from typing import Dict, List, Optional


class OKXClient:
    def __init__(self, api_key: str, secret_key: str, passphrase: str, simulated: bool = False):
        flag = "1" if simulated else "0"
        self.account = Account(api_key, secret_key, passphrase, flag=flag)
        self.funding = FundingAccount(api_key, secret_key, passphrase, flag=flag)
        self.market = Market(flag=flag)

    def get_balance(self) -> List[Dict]:
        result = self.account.get_balance()
        if result.get("code") != "0":
            raise Exception(f"OKX API error (balance): {result}")
        data = result.get("data", [])
        if not data:
            return []
        details = data[0].get("details", [])
        return [
            {
                "currency": d["ccy"],
                "equity": float(d.get("eq", 0)),
                "available": float(d.get("availBal", 0)),
                "frozen": float(d.get("frozenBal", 0)),
                "cash_balance": float(d.get("cashBal", 0)),
                "usd_eq": float(d.get("eqUsd", 0)),
            }
            for d in details
            if float(d.get("eq", 0)) > 0
        ]

    def get_positions(self) -> List[Dict]:
        result = self.account.get_positions()
        if result.get("code") != "0":
            raise Exception(f"OKX API error (positions): {result}")
        data = result.get("data", [])
        return [
            {
                "inst_id": p["instId"],
                "pos": float(p["pos"]),
                "pos_ccy": p.get("posCcy", ""),
                "avg_px": float(p.get("avgPx", 0)),
                "upl": float(p.get("upl", 0)),
                "upl_ratio": float(p.get("uplRatio", 0)) * 100,
                "margin": float(p.get("imr", 0)),
                "lever": float(p.get("lever", 1)),
                "pos_side": p.get("posSide", ""),
                "inst_type": p.get("instType", ""),
                "mark_px": float(p.get("markPx", 0)),
                "liq_px": float(p.get("liqPx", 0)),
                "notional_usd": float(p.get("notionalUsd", 0)),
            }
            for p in data
            if float(p.get("pos", 0)) != 0
        ]

    def get_funding_balances(self) -> List[Dict]:
        result = self.funding.get_balances()
        if result.get("code") != "0":
            raise Exception(f"OKX API error (funding): {result}")
        data = result.get("data", [])
        return [
            {
                "currency": d["ccy"],
                "balance": float(d["bal"]),
                "available": float(d.get("availBal", 0)),
                "frozen": float(d.get("frozenBal", 0)),
            }
            for d in data
            if float(d.get("bal", 0)) > 0
        ]

    def get_account_config(self) -> Dict:
        result = self.account.get_config()
        if result.get("code") != "0":
            return {"unified": False, "acctLv": "1"}
        data = result.get("data", [])
        if not data:
            return {"unified": False, "acctLv": "1"}
        acct_mode = data[0].get("acctMode", "0")
        acct_lv = data[0].get("acctLv", "1")
        return {"unified": acct_mode == "1", "acctLv": acct_lv}

    def detect_account_type(self) -> str:
        try:
            cfg = self.get_account_config()
            acct_lv = int(cfg.get("acctLv", "1"))
            return "futures" if acct_lv >= 2 else "spot"
        except Exception:
            return "spot"

    def get_ticker(self, inst_id: str) -> Optional[Dict]:
        result = self.market.get_ticker(instId=inst_id)
        if result.get("code") != "0":
            return None
        data = result.get("data", [])
        if not data:
            return None
        d = data[0]
        return {
            "inst_id": d["instId"],
            "last": float(d.get("last", 0)),
            "bid": float(d.get("bid", 0)),
            "ask": float(d.get("ask", 0)),
            "vol24h": float(d.get("volCcy24h", 0)),
            "high24h": float(d.get("high24h", 0)),
            "low24h": float(d.get("low24h", 0)),
            "change24h": float(d.get("change24h", 0)),
        }


def get_account_summary(cfg: Dict) -> Dict:
    client = OKXClient(
        cfg["api_key"], cfg["secret_key"],
        cfg["passphrase"], cfg.get("simulated", False),
    )
    balances = client.get_balance()
    positions = client.get_positions()
    funding = client.get_funding_balances()
    try:
        acct_config = client.get_account_config()
    except Exception:
        acct_config = {"unified": False}

    total_equity = sum(b.get("usd_eq", b["equity"]) for b in balances)
    total_pnl = sum(p["upl"] for p in positions)
    usd_in_funding = sum(f["balance"] for f in funding)

    return {
        "name": cfg["name"],
        "type": cfg.get("account_type", "spot"),
        "commission_rate": cfg.get("commission_rate", 0),
        "unified": acct_config.get("unified", False),
        "balances": balances,
        "positions": positions,
        "funding": funding,
        "total_equity": total_equity,
        "unrealized_pnl": total_pnl,
        "funding_balance": usd_in_funding,
        "balance_count": len(balances),
        "position_count": len(positions),
    }
