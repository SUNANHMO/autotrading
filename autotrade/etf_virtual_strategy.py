"""ETF 가상 전략: 실제 주문/잔고와 무관하게 수급 이력을 재생한다.

읽기 전용 순수 함수. 주문/파일/API 접근 없음.
"""
from datetime import datetime

from etf_recovery import parse_amount
from etf_dc20 import update


def replay_virtual_strategy(rows, *, now_time=None):
    if not isinstance(rows, list) or not rows:
        raise ValueError('검증된 당일 수급 이력 필요')
    if now_time is not None:
        datetime.strptime(now_time, '%H%M%S')
    position = 'NONE'
    high = low = current = None
    day_high = day_low = None
    last_time = None
    transitions = []
    seen = set()
    for row in sorted(rows, key=lambda x: x['tm']):
        tm = row['tm']
        if not isinstance(tm, str) or len(tm) != 6 or not tm.isdigit():
            raise ValueError('수급 시간 형식 오류')
        datetime.strptime(tm, '%H%M%S')
        if tm in seen:
            raise ValueError('중복 수급 시각')
        seen.add(tm)
        if tm < '090000' or tm >= '152000':
            continue
        if now_time is not None and tm > now_time:
            raise ValueError('미래 수급 행')
        net = parse_amount(row['prm_netprps_amt'])
        buy = parse_amount(row['prm_buy_amt'])
        sell = parse_amount(row['prm_sell_amt'])
        if buy < 0 or sell < 0 or net != buy - sell:
            raise ValueError('수급 금액 검증 실패')
        current, last_time = net, tm
        day_high = net if day_high is None else max(day_high, net)
        day_low = net if day_low is None else min(day_low, net)
        target, high, low = update(position, net, day_high, day_low, high, low)
        if target:
            transitions.append({'time': tm, 'from': position, 'to': target, 'net': net})
            position = target
            high = low = net
    return {'position': position, 'high_net_amount': high,
            'low_net_amount': low, 'current_net_amount': current,
            'last_time': last_time, 'transitions': transitions,
            'can_submit_order': False}


def plan_virtual_alignment(*, virtual_position, account_position, account_qty,
                           unfilled_orders, now_time, account_verified=False,
                           orders_verified=False):
    """상태 판정만 반환. 실제 취소/매매는 수행하지 않는다."""
    if not account_verified or not orders_verified:
        return 'VERIFY_ACCOUNT_AND_ORDERS'
    if virtual_position not in ('NONE', 'KODEX200', 'INVERSE'):
        return 'INVALID_VIRTUAL_STATE'
    if account_position not in ('NONE', 'KODEX200', 'INVERSE') or type(account_qty) is not int or account_qty < 0:
        return 'INVALID_ACCOUNT_STATE'
    if not isinstance(unfilled_orders, list):
        return 'VERIFY_ACCOUNT_AND_ORDERS'
    if not isinstance(now_time, str) or len(now_time) != 6 or not now_time.isdigit():
        return 'INVALID_TIME'
    try:
        datetime.strptime(now_time, '%H%M%S')
    except ValueError:
        return 'INVALID_TIME'
    if now_time >= '152000':
        if unfilled_orders:
            return 'CLOSING_CANCEL_THEN_VERIFY'
        return 'CLOSING_SELL_IF_HELD' if account_qty else 'CLOSING_VERIFY_ZERO'
    if now_time < '090000':
        return 'OUTSIDE_MARKET_HOURS'
    if account_position == virtual_position:
        if unfilled_orders:
            # 취소 대상은 실제 매도 미체결로 확인된 주문에 한한다.
            if len(unfilled_orders) != 1:
                return 'VERIFY_ORDER_SIDE'
            order = unfilled_orders[0]
            side = order.get('side_raw') if isinstance(order, dict) else None
            if not isinstance(side, dict) or '매도' not in str(side.get('io_tp_nm', '')):
                return 'VERIFY_ORDER_SIDE'
            if order.get('code') != {'KODEX200': '069500', 'INVERSE': '114800'}.get(account_position):
                return 'VERIFY_ORDER_SIDE'
            return 'CANCEL_STALE_SELL'
        return 'ALIGNED_HOLD'
    if unfilled_orders:
        return 'WAIT_EXISTING_ORDER'
    if account_position == 'NONE':
        return 'EVALUATE_NEW_BUY'
    return 'EVALUATE_SWITCH_SELL'
