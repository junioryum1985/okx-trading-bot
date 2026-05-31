from okx.api.trade import Trade
from okx.api.account import Account
from okx.api.market import Market
from typing import Dict, List, Optional
from .database import add_trade, close_trade


class Trader:
    def __init__(self, api_key: str, secret_key: str, passphrase: str, simulated: bool = False):
        flag = "1" if simulated else "0"
        self.trade = Trade(api_key, secret_key, passphrase, flag=flag)
        self.account = Account(api_key, secret_key, passphrase, flag=flag)
        self.market = Market(flag=flag)

    def get_current_price(self, inst_id: str) -> Optional[float]:
        result = self.market.get_ticker(instId=inst_id)
        if result.get("code") != "0":
            return None
        data = result.get("data", [])
        if not data:
            return None
        return float(data[0].get("last", 0))

    def set_leverage(self, inst_id: str, leverage: int, mgn_mode: str = "isolated",
                     pos_side: str = "", ccy: str = "") -> Dict:
        kwargs = dict(instId=inst_id, lever=str(leverage), mgnMode=mgn_mode)
        if pos_side:
            kwargs["posSide"] = pos_side
        if ccy:
            kwargs["ccy"] = ccy
        result = self.account.set_leverage(**kwargs)
        return result

    def _place_order(self, inst_id: str, side: str, pos_side: str,
                     size: float, td_mode: str, ord_type: str,
                     price: Optional[float] = None,
                     tp_px: str = "", sl_px: str = "",
                     ccy: str = "") -> Dict:
        params = {
            "instId": inst_id, "tdMode": td_mode,
            "side": side, "ordType": ord_type,
            "sz": str(size),
        }
        if pos_side:
            params["posSide"] = pos_side
        if price:
            params["px"] = str(price)
        if ccy:
            params["ccy"] = ccy

        algo_ords = []
        if tp_px:
            algo_ords.append({"tpTriggerPx": tp_px, "tpOrdPx": "-1"})
        if sl_px:
            algo_ords.append({"slTriggerPx": sl_px, "slOrdPx": "-1"})
        if algo_ords:
            params["attachAlgoOrds"] = algo_ords

        return self.trade.send_request("/api/v5/trade/order", "POST",
                                        proxies={}, proxy_host=None, **params)

    def get_positions(self, inst_type: str = "SWAP") -> List[Dict]:
        result = self.account.get_positions(instType=inst_type)
        if result.get("code") != "0":
            return []
        return result.get("data", [])

    def close_position(self, inst_id: str, mgn_mode: str = "isolated") -> Dict:
        params = {"instId": inst_id, "mgnMode": mgn_mode}
        result = self.trade.send_request("/api/v5/trade/close-position", "POST",
                                         proxies={}, proxy_host=None, **params)
        return result

    def get_algo_orders(self, inst_id: str = "") -> List[Dict]:
        params = {"instType": "SWAP", "ordType": "conditional"}
        if inst_id:
            params["instId"] = inst_id
        result = self.trade.send_request("/api/v5/trade/orders-algo-pending", "GET",
                                         proxies={}, proxy_host=None, **params)
        if result.get("code") != "0":
            return []
        return result.get("data", [])

    def cancel_algo_orders(self, algo_ids: List[Dict]) -> Dict:
        result = self.trade.send_request("/api/v5/trade/cancel-algos", "POST",
                                         algo_ids, proxies={}, proxy_host=None)
        return result

    def set_tp_sl(self, inst_id: str, side: str, sz: str,
                  tp_px: str = "", sl_px: str = "",
                  td_mode: str = "isolated") -> Dict:
        params = {
            "instId": inst_id, "tdMode": td_mode,
            "side": side, "sz": sz, "ordType": "conditional",
        }
        if tp_px:
            params["tpTriggerPx"] = tp_px
            params["tpOrdPx"] = "-1"
        if sl_px:
            params["slTriggerPx"] = sl_px
            params["slOrdPx"] = "-1"
        result = self.trade.send_request("/api/v5/trade/order-algo", "POST",
                                         proxies={}, proxy_host=None, **params)
        return result

    def get_pending_orders(self, inst_id: str = "") -> List[Dict]:
        params = {"instType": "SWAP"}
        if inst_id:
            params["instId"] = inst_id
        result = self.trade.get_orders_pending(**params)
        if result.get("code") != "0":
            return []
        return result.get("data", [])

    def cancel_orders(self, orders: List[Dict]) -> Dict:
        result = self.trade.set_cancel_batch_orders(orders)
        return result


def execute_trade(cfg: Dict, inst_id: str, direction: str, entry_amount: float,
                  leverage: int = 1, order_type: str = "market",
                  limit_price: Optional[float] = None,
                  tp_price: Optional[float] = None,
                  sl_price: Optional[float] = None,
                  td_mode: str = "isolated") -> Dict:
    trader = Trader(
        cfg["api_key"], cfg["secret_key"],
        cfg["passphrase"], cfg.get("simulated", False),
    )

    side = "buy" if direction == "long" else "sell"
    is_net_mode = td_mode in ("cash", "inverse")
    pos_side = "" if is_net_mode else ("long" if direction == "long" else "short")

    current_price = trader.get_current_price(inst_id)
    if current_price is None:
        return {"success": False, "error": "Não foi possível obter o preço do instrumento"}

    # Derive base/quote currency from instrument ID
    parts = inst_id.split("-")
    base_ccy = parts[0]
    quote_ccy = parts[1]
    ccy = base_ccy if side == "sell" else quote_ccy

    is_inverse = td_mode == "inverse"
    actual_td_mode = "isolated" if is_inverse else td_mode

    if leverage > 1 and actual_td_mode != "cash":
        lev_result = trader.set_leverage(inst_id, leverage, mgn_mode=actual_td_mode,
                                         pos_side=pos_side, ccy=ccy if not is_inverse else base_ccy)
        if lev_result.get("code") not in ("0", "1"):
            pass

    # Auto-corrige TP/SL trocados conforme direção
    if tp_price and sl_price:
        if direction == "long" and tp_price < sl_price:
            tp_price, sl_price = sl_price, tp_price
        elif direction == "short" and tp_price > sl_price:
            tp_price, sl_price = sl_price, tp_price

    tp_px = str(round(tp_price, 2)) if tp_price else ""
    sl_px = str(round(sl_price, 2)) if sl_price else ""

    total_for_trade = entry_amount * leverage

    if is_inverse:
        size = total_for_trade
    elif td_mode == "cash" and side == "buy" and order_type == "market":
        size = total_for_trade
    else:
        size = total_for_trade / current_price
    size = round(size, 6)

    if size <= 0:
        return {"success": False, "error": "Tamanho da entrada muito pequeno"}

    order_ccy = ccy if actual_td_mode != "cash" else ""

    if order_type == "market":
        result = trader._place_order(inst_id, side, pos_side, size,
                                     td_mode=actual_td_mode, ord_type="market",
                                     tp_px=tp_px, sl_px=sl_px, ccy=order_ccy)
    else:
        if limit_price is None:
            return {"success": False, "error": "Preço limite não especificado"}
        result = trader._place_order(inst_id, side, pos_side, size,
                                     td_mode=actual_td_mode, ord_type="limit",
                                     price=limit_price,
                                     tp_px=tp_px, sl_px=sl_px, ccy=order_ccy)

    if result.get("code") == "0":
        order_id = result["data"][0].get("ordId", "")
        entry_px = current_price if order_type == "market" else limit_price
        trade_id = add_trade(
            api_id=cfg.get("id", 0),
            api_name=cfg["name"],
            inst_id=inst_id,
            side=side,
            pos_side=pos_side,
            size=size,
            entry_price=entry_px,
            commission_rate=cfg.get("commission_rate", 0),
        )
        return {
            "success": True,
            "order_id": order_id,
            "entry_price": entry_px,
            "size": size,
            "trade_id": trade_id,
            "direction": direction,
            "leverage": leverage,
        }
    else:
        err = result.get("msg", "Erro desconhecido")
        data_list = result.get("data", [])
        if data_list:
            s_msg = data_list[0].get("sMsg", "")
            if s_msg:
                err = f"{err} | {s_msg}"
        return {
            "success": False,
            "error": err,
            "details": result,
        }
