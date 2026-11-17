"""ETF 실제 계좌를 가상 목표에 맞추는 단순 실행 엔진.

지정가 주문은 호가를 추격하지 않는다. 체결 가정은 전략 시뮬레이션용이며,
실계좌에서는 잔고/미체결을 확인한 후 다음 주문을 낸다.
"""
from d_account import get_account, _parse_holdings
from c2_program import get_etf_unfilled_orders
from f_order import (etf_buy, etf_sell, etf_market_sell,
                     etf_cancel_order, get_etf_buy_qty)
from etf_state import load_state, save_state

CODES = {"KODEX200": "069500", "INVERSE": "114800"}


def _account_qty(token):
    account = get_account(token)
    if not isinstance(account, dict) or not isinstance(account.get("stk_acnt_evlt_prst"), list):
        return None
    holdings = _parse_holdings(account)
    # 재시작 직후 주도주 상태 파일이 비어 있어도 실제 주도주 보유를 우선한다.
    if any(h["code"] not in CODES.values() for h in holdings):
        return "LEAD_HOLDING"
    return {code: next((h["qty"] for h in holdings if h["code"] == code), 0)
            for code in CODES.values()}


def _quote(websocket, code):
    if websocket is None or not getattr(websocket, "connected", False):
        return None
    q = websocket.get_etf_quote(code, max_age_seconds=3)
    if not q:
        return None
    bid, ask = int(q.get("best_bid") or 0), int(q.get("best_ask") or 0)
    return (bid, ask) if bid > 0 and ask > 0 else None


def reconcile_etf(token, websocket, target, *, lead_priority=False, closing=False):
    """한 번 호출할 때 최대 한 건의 신규 주문/취소 요청만 실행한다."""
    if target not in ("NONE", *CODES):
        return "INVALID_TARGET"
    state = load_state()
    qty = _account_qty(token)
    orders = get_etf_unfilled_orders(token)
    if qty is None or orders is None:
        return "WAIT_ACCOUNT"
    if qty == "LEAD_HOLDING" and not closing:
        return "LEAD_PRIORITY"
    if qty == "LEAD_HOLDING":
        return "WAIT_LEAD_HOLDING"
    # 장중에는 미체결 주문을 취소하거나 정정하지 않는다. 신호가 바뀌어도 대기.
    if orders:
        if not closing:
            return "WAIT_FILL"
        # 이미 접수한 마감 시장가 매도는 절대 취소하지 않는다.
        closing_no = str(state.get("closing_order_no") or "")
        if closing_no and any(str(o.get("ord_no") or "") == closing_no for o in orders):
            return "WAIT_CLOSING_FILL"
        if state.get("cancel_requested"):
            return "WAIT_CANCEL"
        for order in orders:
            code = str(order.get("stk_cd", "")).removeprefix("A").strip()
            number = order.get("ord_no")
            if not number:
                return "WAIT_ORDER_NUMBER"
            result = etf_cancel_order(token, code, number)
            if result is None:
                return "WAIT_CANCEL_REQUEST"
            state.update(cancel_requested=True, pending_order_no=str(number))
            save_state(state)
            return "CANCEL_REQUESTED"
    if state.get("cancel_requested"):
        state.update(cancel_requested=False, pending_order_no=None)
        save_state(state)
        return "RECHECK_AFTER_CANCEL"
    if closing:
        # 장마감에는 장중 고정가격 계획을 폐기하고 기존 시장가 청산을 수행한다.
        if state.get("active_stage"):
            state.update(active_target=None, active_sell_code=None,
                         active_sell_price=None, active_buy_price=None, active_stage=None)
            save_state(state)
        if state.get("closing_order_no"):
            closing_code = state.get("closing_code")
            if closing_code and qty.get(closing_code, 0) == 0:
                state.update(closing_order_no=None, closing_code=None)
                save_state(state)
            else:
                return "WAIT_CLOSING_FILL"
        for code, held in qty.items():
            if held > 0:
                number = etf_market_sell(token, code, held)
                if number:
                    state.update(closing_order_no=str(number), closing_code=code)
                    save_state(state)
                return "CLOSING_SELL_SUBMITTED" if number else "CLOSING_SELL_FAILED"
        return "CLOSING_FLAT"

    # 이미 시작한 전환은 최초 신호 가격으로 끝낸다.
    stage = state.get("active_stage")
    if stage == "SELL":
        sell_code = state.get("active_sell_code")
        if sell_code and qty.get(sell_code, 0) > 0:
            # 주문이 사라졌는데 잔고가 남았다면 중복 매도를 피한다.
            return "WAIT_SELL_BALANCE"
        state["active_stage"] = "BUY"
        save_state(state)
        stage = "BUY"
    if stage == "BUY":
        active_target = state.get("active_target")
        if active_target not in CODES:
            return "INVALID_ACTIVE_TARGET"
        code = CODES[active_target]
        if qty[code] > 0:
            state.update(active_target=None, active_sell_code=None,
                         active_sell_price=None, active_buy_price=None, active_stage=None)
            save_state(state)
            return "SWITCH_COMPLETED"
        price = int(state.get("active_buy_price") or 0)
        if price <= 0:
            return "WAIT_SIGNAL_PRICE"
        buy_qty = get_etf_buy_qty(token, code, price)
        if buy_qty <= 0:
            return "WAIT_BUY_POWER"
        number = etf_buy(token, code, buy_qty, price)
        return "BUY_SUBMITTED" if number else "BUY_FAILED"

    if lead_priority or target == "NONE":
        return "LEAD_PRIORITY" if lead_priority else "NO_SIGNAL"
    desired = CODES[target]
    if qty[desired] > 0 and all(qty[c] == 0 for c in CODES.values() if c != desired):
        return "ALIGNED"
    # 신호 발생 당시 텔레그램에 기록된 호가만 사용한다.
    prices = state.get("signal_prices") or {}
    if state.get("signal_target") != target:
        return "WAIT_SIGNAL_PRICE"
    buy_price = int((prices.get(target) or {}).get("bid") or 0)
    if buy_price <= 0:
        return "WAIT_SIGNAL_PRICE"
    for code, held in qty.items():
        if code != desired and held > 0:
            old_target = next(name for name, value in CODES.items() if value == code)
            sell_price = int((prices.get(old_target) or {}).get("ask") or 0)
            if sell_price <= 0:
                return "WAIT_SIGNAL_PRICE"
            number = etf_sell(token, code, held, sell_price)
            if number:
                state.update(active_target=target, active_sell_code=code,
                             active_sell_price=sell_price, active_buy_price=buy_price,
                             active_stage="SELL")
                save_state(state)
            return "SELL_SUBMITTED" if number else "SELL_FAILED"
    # 최초 진입도 신호 당시 매수호가로 고정한다.
    buy_qty = get_etf_buy_qty(token, desired, buy_price)
    if buy_qty <= 0:
        return "WAIT_BUY_POWER"
    number = etf_buy(token, desired, buy_qty, buy_price)
    if number:
        state.update(active_target=target, active_sell_code=None,
                     active_sell_price=None, active_buy_price=buy_price, active_stage="BUY")
        save_state(state)
    return "BUY_SUBMITTED" if number else "BUY_FAILED"
