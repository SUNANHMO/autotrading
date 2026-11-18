"""20단계: 15:20 ETF 청산 순서의 읽기 전용 안전 판정.

주문/API/상태변경 없음. 취소 요청 접수만으로 완료 인정 금지.
"""
from datetime import datetime

ETF_CODES = frozenset(('069500', '114800'))


def plan_etf_closing(*, now_time, holdings, unfilled_orders,
                     account_verified=False, orders_verified=False,
                     cancel_pending=False, cancel_proof_verified=False,
                     closing_order_pending=False, closing_order_verified=False):
    result = {'action': 'VERIFY_INPUTS', 'can_submit_order': False,
              'actual_code': None, 'actual_qty': None, 'pending_count': None}
    flags = (account_verified, orders_verified, cancel_pending,
             cancel_proof_verified, closing_order_pending, closing_order_verified)
    if any(type(x) is not bool for x in flags):
        return result
    if not isinstance(now_time, str) or len(now_time) != 6 or not now_time.isdigit():
        return result
    try:
        datetime.strptime(now_time, '%H%M%S')
    except ValueError:
        return result
    if now_time < '152000':
        result['action'] = 'WAIT_FOR_1520'
        return result
    if not account_verified or not orders_verified:
        result['action'] = 'VERIFY_ACCOUNT_AND_ORDERS'
        return result
    if (not isinstance(holdings, list) or not isinstance(unfilled_orders, list)
            or any(not isinstance(x, dict) for x in holdings + unfilled_orders)):
        return result
    try:
        qty_by_code = dict.fromkeys(ETF_CODES, 0)
        seen_holdings = set()
        for row in holdings:
            code = str(row.get('stk_cd', '')).strip().removeprefix('A')
            if code not in ETF_CODES:
                continue
            if code in seen_holdings:
                raise ValueError('중복 잔고')
            seen_holdings.add(code)
            qty_by_code[code] = _quantity(row.get('rmnd_qty'))
        held = [(code, qty) for code, qty in qty_by_code.items() if qty]
        if len(held) > 1:
            raise ValueError('양방향 ETF 잔고')
        pending = []
        seen_orders = set()
        for row in unfilled_orders:
            code = str(row.get('stk_cd', '')).strip().removeprefix('A')
            if code not in ETF_CODES:
                raise ValueError('ETF 외 주문')
            qty = _quantity(row.get('oso_qty'))
            if not qty:
                continue
            order_no = str(row.get('ord_no', '')).strip()
            if not order_no.isdigit() or len(order_no) > 7:
                raise ValueError('주문번호 불명확')
            order_no = order_no.zfill(7)
            if order_no in seen_orders:
                raise ValueError('중복 주문번호')
            seen_orders.add(order_no)
            side = row.get('io_tp_nm')
            if not isinstance(side, str) or ('매수' in side) == ('매도' in side):
                raise ValueError('주문 방향 불명확')
            pending.append((code, qty, side))
        result.update(actual_code=held[0][0] if held else None,
                      actual_qty=held[0][1] if held else 0,
                      pending_count=len(pending))
    except (TypeError, ValueError):
        return result

    if closing_order_pending:
        result['action'] = 'VERIFY_EXISTING_CLOSING_ORDER'
    elif cancel_pending:
        result['action'] = 'VERIFY_PENDING_CANCEL'
    elif pending:
        result['action'] = 'CANCEL_PENDING_ORDERS_THEN_VERIFY'
    elif not cancel_proof_verified:
        # 취소가 필요 없었다는 별도 근거까지 호출자가 확인해야 함.
        result['action'] = 'VERIFY_CANCELLATION_OR_NO_CANCEL_NEEDED'
    elif now_time >= '153000':
        result['action'] = 'VERIFY_AFTER_CLOSE_BALANCE'
    elif closing_order_verified:
        result['action'] = 'VERIFY_EXISTING_CLOSING_ORDER'
    elif result['actual_qty']:
        result['action'] = 'REVIEW_MARKET_SELL_ACTUAL_QTY'
    else:
        result['action'] = 'CLOSING_ZERO_BALANCE_CONFIRMED'
    return result


def _quantity(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('수량 누락')
    raw = str(value).replace(',', '').strip()
    if not raw.isdigit():
        raise ValueError('수량 형식')
    return int(raw)
