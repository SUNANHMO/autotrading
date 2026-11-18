"""19단계: ETF 미체결/부분체결 스냅샷 정합성 검사 (읽기 전용).

실제 계좌 조회의 완전성은 호출자가 확인해야 한다. 반환값은 주문 허가가 아니다.
가상 포지션은 절대 수정하지 않는다.
"""
from etf_virtual_alignment_step18 import plan_virtual_account_alignment

CODES = {'KODEX200': '069500', 'INVERSE': '114800'}


def _qty(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('수량 누락')
    raw = str(value).strip().replace(',', '')
    if not raw.isdigit():
        raise ValueError('수량 형식 불명확')
    return int(raw)


def _side(row):
    raw = row.get('io_tp_nm')
    if isinstance(raw, str):
        if '매도' in raw and '매수' not in raw:
            return 'SELL'
        if '매수' in raw and '매도' not in raw:
            return 'BUY'
    return None


def reconcile_etf_snapshot(*, virtual_position, holdings, unfilled_orders,
                           now_time, account_verified=False, orders_verified=False,
                           lead_blocked=False, cancel_pending=False):
    """holdings: [{stk_cd, rmnd_qty}, ...] 전체 계좌 보유 원문.

    오류나 불완전한 스냅샷은 모두 차단. 주문번호별 미체결 수량은
    '실제 체결 수량'으로 역산하지 않는다(정정/부분취소 가능).
    """
    result = {'status': 'VERIFY_REQUIRED', 'action': 'VERIFY_ACCOUNT_AND_ORDERS',
              'can_submit_order': False, 'virtual_position': virtual_position,
              'actual_position': None, 'actual_qty': None,
              'pending_count': None, 'partial_fill_confirmed': False}
    if (type(account_verified) is not bool or type(orders_verified) is not bool
            or not account_verified or not orders_verified):
        return result
    if (not isinstance(holdings, list) or not isinstance(unfilled_orders, list)
            or any(not isinstance(x, dict) for x in holdings + unfilled_orders)):
        return result
    try:
        quantities = dict.fromkeys(CODES.values(), 0)
        seen_holdings = set()
        for row in holdings:
            code = str(row.get('stk_cd', '')).strip().removeprefix('A')
            if code not in quantities:
                continue
            if code in seen_holdings:
                raise ValueError('중복 ETF 잔고 행')
            seen_holdings.add(code)
            quantities[code] = _qty(row.get('rmnd_qty'))
        held = [code for code, qty in quantities.items() if qty > 0]
        if len(held) > 1:
            raise ValueError('양방향 ETF 동시 보유')
        account_position = next((pos for pos, code in CODES.items() if code in held), 'NONE')
        account_qty = quantities[held[0]] if held else 0
        normalized = []
        seen_orders = set()
        for row in unfilled_orders:
            code = str(row.get('stk_cd', '')).strip().removeprefix('A')
            if code not in quantities:
                raise ValueError('ETF 외 미체결 행 혼입')
            qty = _qty(row.get('oso_qty'))
            if qty == 0:
                continue
            order_no = str(row.get('ord_no', '')).strip()
            if not order_no.isdigit() or len(order_no) > 7:
                raise ValueError('주문번호 불명확')
            order_key = order_no.zfill(7)
            if order_key in seen_orders:
                raise ValueError('중복 주문번호')
            seen_orders.add(order_key)
            side = _side(row)
            if side is None:
                raise ValueError('주문 방향 불명확')
            if side == 'SELL' and quantities[code] == 0:
                # 매도 잔량이 있지만 보유 0이면 잔고/주문 조회 시점 차이 가능
                raise ValueError('매도 미체결과 잔고 불일치')
            normalized.append({'code': code, 'side': side, 'remaining_qty': qty,
                               'order_no': order_key})
        result.update(actual_position=account_position, actual_qty=account_qty,
                      pending_count=len(normalized))
        plan = plan_virtual_account_alignment(
            virtual_position=virtual_position, account_position=account_position,
            account_qty=account_qty, unfilled_orders=unfilled_orders,
            now_time=now_time, account_verified=True, orders_verified=True,
            lead_blocked=lead_blocked, cancel_pending=cancel_pending)
        action = plan['action']
        if action == 'VERIFY_INPUTS':
            return result
        # 미체결 주문이 하나라도 있으면 신규 주문 검토 이전에 주문 상태 확인.
        # stale sell은 18단계의 취소 검토 액션을 그대로 보존.
        result.update(status='SNAPSHOT_CLASSIFIED', action=action,
                      pending_orders=normalized)
        return result
    except (ValueError, TypeError):
        return result
