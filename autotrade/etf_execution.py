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
    # 주문 취소 요청 후에는 미체결 조회에서 사라질 때까지 추가 주문하지 않는다.
    if orders:
        if state.get("cancel_requested"):
            return "WAIT_CANCEL"
        # 장마감 또는 현재 목표와 맞지 않는 주문만 취소한다.
        for order in orders:
            code = str(order.get("stk_cd", "")).removeprefix("A").strip()
            side = str(order.get("io_tp_nm", ""))
            wrong = closing or code != CODES.get(target) or ("매도" in side and qty.get(code, 0) > 0 and code == CODES.get(target))
            if wrong:
                number = order.get("ord_no")
                if not number:
                    return "WAIT_ORDER_NUMBER"
                result = etf_cancel_order(token, code, number)
                if result is None:
                    return "WAIT_CANCEL_REQUEST"
                state.update(cancel_requested=True, pending_order_no=str(number))
                save_state(state)
                return "CANCEL_REQUESTED"
        return "WAIT_FILL"
    if state.get("cancel_requested"):
        state.update(cancel_requested=False, pending_order_no=None)
        save_state(state)
        # 조회 직후 체결/취소 경합 가능성이 있으므로 다음 주기에 잔고 재조회.
        return "RECHECK_AFTER_CANCEL"
    if closing:
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
    if lead_priority or target == "NONE":
        return "LEAD_PRIORITY" if lead_priority else "NO_SIGNAL"
    desired = CODES[target]
    for code, held in qty.items():
        if code != desired and held > 0:
            q = _quote(websocket, code)
            if not q:
                return "WAIT_QUOTE"
            number = etf_sell(token, code, held, q[1])
            return "SELL_SUBMITTED" if number else "SELL_FAILED"
    if qty[desired] > 0:
        return "ALIGNED"
    q = _quote(websocket, desired)
    if not q:
        return "WAIT_QUOTE"
    buy_qty = get_etf_buy_qty(token, desired, q[0])
    if buy_qty <= 0:
        return "WAIT_BUY_POWER"
    number = etf_buy(token, desired, buy_qty, q[0])
    return "BUY_SUBMITTED" if number else "BUY_FAILED"
