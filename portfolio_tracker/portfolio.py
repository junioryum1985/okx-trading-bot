from prettytable import PrettyTable
from .client import OKXClient
from typing import List, Dict


def collect_wallet_data(wallets_cfgs: List[Dict]) -> List[Dict]:
    report = []
    for cfg in wallets_cfgs:
        client = OKXClient(
            api_key=cfg["api_key"],
            secret_key=cfg["secret_key"],
            passphrase=cfg["passphrase"],
            simulated=cfg.get("simulated", False),
        )
        balances = client.get_balance()
        positions = client.get_positions()

        total_usd = sum(b["equity"] for b in balances)
        pnl_positions = sum(p["upl"] for p in positions)

        report.append({
            "name": cfg["name"],
            "balances": balances,
            "positions": positions,
            "total_equity_usd": total_usd,
            "unrealized_pnl": pnl_positions,
            "balance_count": len(balances),
            "position_count": len(positions),
        })
    return report


def print_report(report: List[Dict]):
    summary = PrettyTable()
    summary.field_names = ["Carteira", "Saldo (USD)", "Ativos", "Posições", "PnL Não Realizado"]
    summary.align = "r"
    summary.align["Carteira"] = "l"

    grand_total = 0
    grand_pnl = 0
    for r in report:
        summary.add_row([
            r["name"],
            f"${r['total_equity_usd']:,.2f}",
            r["balance_count"],
            r["position_count"],
            f"${r['unrealized_pnl']:+,.2f}",
        ])
        grand_total += r["total_equity_usd"]
        grand_pnl += r["unrealized_pnl"]

    print("=" * 70)
    print("PORTFOLIO TRACKER - MÚLTIPLAS CARTEIRAS OKX")
    print("=" * 70)
    print()
    print(summary)
    print("-" * 70)
    print(f"{'TOTAL':<20} ${grand_total:>12,.2f}                    ${grand_pnl:>+,.2f}")
    print()

    for r in report:
        if r["balances"]:
            tbl = PrettyTable()
            tbl.field_names = ["Moeda", "Equity (USD)", "Disponível", "Congelado"]
            tbl.align = "r"
            tbl.align["Moeda"] = "l"
            for b in sorted(r["balances"], key=lambda x: x["equity"], reverse=True):
                tbl.add_row([
                    b["currency"],
                    f"${b['equity']:,.2f}",
                    f"{b['available']:.4f}",
                    f"{b['frozen']:.4f}",
                ])
            print(f"\n--- {r['name']} ---")
            print(tbl)

        if r["positions"]:
            ptbl = PrettyTable()
            ptbl.field_names = ["Instrumento", "Posição", "Margem", "Alavancagem", "PnL"]
            ptbl.align = "r"
            ptbl.align["Instrumento"] = "l"
            for p in sorted(r["positions"], key=lambda x: abs(x["upl"]), reverse=True):
                ptbl.add_row([
                    p["inst_id"],
                    p["pos"],
                    f"${p['margin']:,.2f}",
                    f"{p['lever']}x",
                    f"${p['upl']:+,.2f}",
                ])
            print(ptbl)
