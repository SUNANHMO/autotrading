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


def _account_qty(token, *, closing=False):
    account = get_account(token)
    if not isinstance(account, dict) or not isinstance(account.get("stk_acnt_evlt_prst"), list):
        return None
    holdings = _parse_holdings(account)
    # 재시작 직후 주도주 상태 파일이 비어 있어도 실제 주도주 보유를 우선한다.
    if not closing and any(h["code"] not in CODES.values() for h in holdings):
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
    qty = _account_qty(token, closing=closing)
    orders = get_etf_unfilled_orders(token)
    if qty is None or orders is None:
        return "WAIT_ACCOUNT"
    if qty == "LEAD_HOLDING" and not closing:
        # 주도주 보유를 확인한 경우, 이후 전량 매도 시 ETF 재진입을 허용한다.
        if not state.get("etf_waiting_for_lead_exit"):
            state["etf_waiting_for_lead_exit"] = True
            save_state(state)
        return "LEAD_PRIORITY"
    if qty == "LEAD_HOLDING":
        return "WAIT_LEAD_HOLDING"
    # 15:20 이후: 모든 ETF 미체결 주문의 취소 완료를 확인한 뒤 시장가 청산한다.
    # 한 번의 호출에서 주문 요청은 최대 한 건만 실행한다.
    if closing:
        # 장중 전환 계획은 마감 시 폐기한다.
        if state.get("active_stage"):
            state.update(active_target=None, active_sell_code=None,
                         active_sell_price=None, active_buy_price=None, active_stage=None,
                         active_buy_order_no=None)
            save_state(state)

        if orders:
            # 이번 청산 단계에서 직접 제출한 시장가 매도는 중복 취소/재주문하지 않는다.
            closing_no = str(state.get("closing_order_no") or "")
            if closing_no and any(str(o.get("ord_no") or "") == closing_no for o in orders):
                return "WAIT_CLOSING_FILL"
            pending_no = str(state.get("pending_order_no") or "")
            if state.get("cancel_requested") and pending_no:
                if any(str(o.get("ord_no") or "") == pending_no for o in orders):
                    return "WAIT_CANCEL"
                # 취소 대상 주문이 미체결 목록에서 사라졌음: 다음 주문을 처리한다.
                state.update(cancel_requested=False, pending_order_no=None)
                save_state(state)
                return "RECHECK_AFTER_CANCEL"
            elif state.get("cancel_requested"):
                state.update(cancel_requested=False, pending_order_no=None)
                save_state(state)

            for order in orders:
                code = str(order.get("stk_cd") or "").removeprefix("A").strip()
                number = str(order.get("ord_no") or "").strip()
                if code not in CODES.values() or not number:
                    # 알 수 없는 주문은 임의로 취소하거나 건너뛰지 않는다.
                    return "WAIT_ORDER_DETAILS"
                result = etf_cancel_order(token, code, number)
                if result is None:
                    return "WAIT_CANCEL_REQUEST"
                state.update(cancel_requested=True, pending_order_no=number)
                save_state(state)
                return "CANCEL_REQUESTED"

        # 미체결 목록이 비어 있으면 과거 주문번호 때문에 청산을 막지 않는다.
        if state.get("cancel_requested") or state.get("pending_order_no"):
            state.update(cancel_requested=False, pending_order_no=None)
            save_state(state)
            return "RECHECK_AFTER_CANCEL"
        if state.get("closing_order_no") or state.get("closing_code"):
            state.update(closing_order_no=None, closing_code=None)
            save_state(state)

        for code, held in qty.items():
            if held > 0:
                number = etf_market_sell(token, code, held)
                if number:
                    state.update(closing_order_no=str(number), closing_code=code)
                    save_state(state)
                return "CLOSING_SELL_SUBMITTED" if number else "CLOSING_SELL_FAILED"
        return "CLOSING_FLAT"

    # 취소 접수와 완료는 구분한다. 목록에서 사라진 뒤에도 다음 호출에서
    # 잔고와 최신 가상 방향을 다시 조회하고 주문한다.
    if state.get("cancel_requested"):
        pending_no = str(state.get("pending_order_no") or "").strip()
        if not pending_no or any(str(o.get("ord_no") or "").strip() == pending_no
                                 for o in orders):
            return "WAIT_CANCEL"
        state.update(cancel_requested=False, pending_order_no=None,
                     active_target=None, active_sell_code=None,
                     active_sell_price=None, active_buy_price=None,
                     active_stage=None, active_buy_order_no=None)
        save_state(state)
        return "RECHECK_AFTER_CANCEL"

    stage = state.get("active_stage")
    active_target = state.get("active_target")
    stale_buy = (stage == "BUY" and active_target in CODES
                 and target in CODES and target != active_target)
    if orders:
        if not stale_buy:
            return "WAIT_FILL"
        # 자동매매가 제출한 주문번호가 확인된 매수 주문만 취소한다.
        # 구버전 주문번호가 없으면 수동 주문과 구분할 수 없어 대기한다.
        old_code = CODES[active_target]
        tracked = str(state.get("active_buy_order_no") or "").strip()
        for order in orders:
            code = str(order.get("stk_cd") or "").removeprefix("A").strip()
            number = str(order.get("ord_no") or "").strip()
            if code != old_code or not number or not tracked or number != tracked:
                continue
            if etf_cancel_order(token, code, number) is None:
                return "WAIT_CANCEL_REQUEST"
            state.update(cancel_requested=True, pending_order_no=number)
            save_state(state)
            return "CANCEL_REQUESTED"
        return "WAIT_ORDER_DETAILS"

    # 주문이 이미 체결되었거나 취소된 경우에도 낡은 매수 계획은 폐기한다.
    # 잔고를 기준으로 최신 신호 가격의 정상 전환 경로를 사용한다.
    if stale_buy or (stage == "SELL" and target in CODES
                     and active_target in CODES and target != active_target):
        state.update(active_target=None, active_sell_code=None,
                     active_sell_price=None, active_buy_price=None,
                     active_stage=None, active_buy_order_no=None)
        save_state(state)
        stage = None

    # 유효한 전환은 최초 신호 가격으로 끝낸다.
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
                         active_sell_price=None, active_buy_price=None, active_stage=None,
                         active_buy_order_no=None)
            save_state(state)
            return "SWITCH_COMPLETED"
        price = int(state.get("active_buy_price") or 0)
        if price <= 0:
            return "WAIT_SIGNAL_PRICE"
        buy_qty = get_etf_buy_qty(token, code, price)
        if buy_qty <= 0:
            return "WAIT_BUY_POWER"
        number = etf_buy(token, code, buy_qty, price)
        if number:
            state["active_buy_order_no"] = str(number)
            save_state(state)
        return "BUY_SUBMITTED" if number else "BUY_FAILED"

    if lead_priority or target == "NONE":
        return "LEAD_PRIORITY" if lead_priority else "NO_SIGNAL"
    desired = CODES[target]
    if qty[desired] > 0 and all(qty[c] == 0 for c in CODES.values() if c != desired):
        if state.get("etf_waiting_for_lead_exit"):
            state["etf_waiting_for_lead_exit"] = False
            save_state(state)
        return "ALIGNED"

    # 주도주 보유를 관측한 뒤 매도가 완료되어 ETF 잔고가 없는 경우에만,
    # 과거 신호 가격 대신 현재 웹소켓의 최신 최우선 매수호가를 사용한다.
    # 미체결/계좌 오류/주도주 우선 상태는 위에서 이미 차단한다.
    if (state.get("etf_waiting_for_lead_exit")
            and all(held == 0 for held in qty.values())):
        quote = _quote(websocket, desired)
        if quote is None:
            return "WAIT_LEAD_EXIT_QUOTE"
        buy_price = quote[0]
        buy_qty = get_etf_buy_qty(token, desired, buy_price)
        if buy_qty <= 0:
            return "WAIT_BUY_POWER"
        number = etf_buy(token, desired, buy_qty, buy_price)
        if number:
            state.update(active_target=target, active_sell_code=None,
                         active_sell_price=None, active_buy_price=buy_price,
                         active_stage="BUY", active_buy_order_no=str(number),
                         etf_waiting_for_lead_exit=False)
            save_state(state)
        return "BUY_SUBMITTED" if number else "BUY_FAILED"

    # 일반 ETF 전환/최초 진입은 기존 신호 당시 가격을 그대로 사용한다.
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
            # 최초 가상 진입인데 실제 반대 ETF 잔고가 남아 있으면
            # 해당 매도 호가만 추가 확보하고 기존 매수 가격은 유지한다.
            if sell_price <= 0 and state.get("signal_initial_entry"):
                quote = _quote(websocket, code)
                if quote is not None:
                    sell_price = quote[1]
                    prices[old_target] = {"bid": quote[0], "ask": quote[1]}
                    state["signal_prices"] = prices
                    save_state(state)
            if sell_price <= 0:
                return "WAIT_SIGNAL_PRICE"
            number = etf_sell(token, code, held, sell_price)
            if number:
                state.update(active_target=target, active_sell_code=code,
                             active_sell_price=sell_price, active_buy_price=buy_price,
                             active_stage="SELL", active_buy_order_no=None)
                save_state(state)
            return "SELL_SUBMITTED" if number else "SELL_FAILED"
    # 최초 진입도 신호 당시 매수호가로 고정한다.
    buy_qty = get_etf_buy_qty(token, desired, buy_price)
    if buy_qty <= 0:
        return "WAIT_BUY_POWER"
    number = etf_buy(token, desired, buy_qty, buy_price)
    if number:
        state.update(active_target=target, active_sell_code=None,
                     active_sell_price=None, active_buy_price=buy_price, active_stage="BUY",
                     active_buy_order_no=str(number))
        save_state(state)
    return "BUY_SUBMITTED" if number else "BUY_FAILED"
