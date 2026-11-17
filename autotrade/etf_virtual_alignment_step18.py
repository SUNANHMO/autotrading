"""18단계: 가상 ETF 목표와 실계좌/미체결 스냅샷의 순수 정합성 판정.

주문 실행, API 호출, 상태 저장 없음. 모든 결과에서 can_submit_order=False.
가상 포지션의 갱신은 etf_virtual_strategy.replay_virtual_strategy가 담당하며,
이 판정기는 가상 포지션을 실제 계좌/주문에 맞춰 변경하지 않는다.
"""
from datetime import datetime

CODES = {'KODEX200': '069500', 'INVERSE': '114800'}
POSITIONS = frozenset(('NONE', 'KODEX200', 'INVERSE'))


def _code(value):
    raw = str(value or '').strip()
    return raw[1:] if raw.startswith('A') else raw


def _side(row):
    # 실제 ka10075 필드; 모호하면 주문 방향을 추측하지 않는다.
    raw = row.get('io_tp_nm')
    if raw is None:
        raw = row.get('side_raw')
        if isinstance(raw, dict):
            raw = raw.get('io_tp_nm')
    if not isinstance(raw, str):
        return None
    if '매도' in raw and '매수' not in raw:
        return 'SELL'
    if '매수' in raw and '매도' not in raw:
        return 'BUY'
    return None


def plan_virtual_account_alignment(*, virtual_position, account_position,
                                   account_qty, unfilled_orders, now_time,
                                   account_verified=False, orders_verified=False,
                                   lead_blocked=False, cancel_pending=False):
    """완전성 확인된 스냅샷으로 다음 *검증/판단* 작업만 반환.

    unfilled_orders: ka10075의 ETF 미체결 원문 행 리스트.
    실제 주문 승인과 무관하며 가상 포지션을 절대 수정하지 않는다.
    """
    out = {'virtual_position': virtual_position,
           'account_position': account_position,
           'action': 'VERIFY_INPUTS', 'reason': '', 'can_submit_order': False}
    flags = (account_verified, orders_verified, lead_blocked, cancel_pending)
    if any(type(flag) is not bool for flag in flags):
        out['reason'] = '검증 플래그 형식 오류'
        return out
    if not account_verified or not orders_verified:
        out['action'] = 'VERIFY_ACCOUNT_AND_ORDERS'
        return out
    if (virtual_position not in POSITIONS or account_position not in POSITIONS
            or type(account_qty) is not int or account_qty < 0
            or (account_position == 'NONE') != (account_qty == 0)):
        out['reason'] = '가상/실계좌 포지션 또는 잔고 불일치'
        return out
    if not isinstance(now_time, str) or len(now_time) != 6 or not now_time.isdigit():
        return out
    try:
        datetime.strptime(now_time, '%H%M%S')
    except ValueError:
        return out
    if not isinstance(unfilled_orders, list) or any(not isinstance(x, dict) for x in unfilled_orders):
        return out

    pending = []
    try:
        for row in unfilled_orders:
            code = _code(row.get('stk_cd'))
            if code not in CODES.values():
                # 호출자가 ETF 전용으로 필터링하지 않았으면 스냅샷을 신뢰하지 않는다.
                raise ValueError('ETF 외 주문 혼입')
            raw_qty = row.get('oso_qty')
            if isinstance(raw_qty, bool) or raw_qty is None:
                raise ValueError('미체결 수량 누락')
            s = str(raw_qty).replace(',', '').strip()
            if not s.isdigit():
                raise ValueError('미체결 수량 형식 오류')
            qty = int(s)
            if qty > 0:
                side = _side(row)
                if side is None:
                    raise ValueError('매수/매도 불명확')
                pending.append((code, side, qty))
    except ValueError as exc:
        out['reason'] = str(exc)
        return out

    if cancel_pending:
        out['action'] = 'VERIFY_PENDING_CANCEL'
    elif now_time >= '152000':
        out['action'] = ('CLOSING_CANCEL_THEN_VERIFY' if pending else
                         'CLOSING_SELL_IF_HELD' if account_qty else 'CLOSING_VERIFY_ZERO')
    elif now_time < '090000':
        out['action'] = 'OUTSIDE_ENTRY_WINDOW'
    elif lead_blocked:
        out['action'] = 'LEAD_PRIORITY_WAIT'
    elif pending:
        # 방향이 가상 목표와 같더라도 미체결 매도가 있으면 취소 확인이 우선.
        expected_code = CODES.get(account_position)
        if (virtual_position == account_position != 'NONE'
                and len(pending) == 1 and pending[0][0] == expected_code
                and pending[0][1] == 'SELL'):
            out['action'] = 'REVIEW_STALE_SELL_CANCEL'
        else:
            out['action'] = 'VERIFY_EXISTING_ORDER'
    elif virtual_position == account_position:
        out['action'] = 'ALIGNED_FLAT' if account_position == 'NONE' else 'ALIGNED_HOLD'
    elif account_position == 'NONE':
        out['action'] = 'REVIEW_INITIAL_BUY' if virtual_position != 'NONE' else 'ALIGNED_FLAT'
    elif virtual_position == 'NONE':
        out['action'] = 'REVIEW_EXIT_TO_FLAT'
    else:
        out['action'] = 'REVIEW_SWITCH_SELL'
    return out
