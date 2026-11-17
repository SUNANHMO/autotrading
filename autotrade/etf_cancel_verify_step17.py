"""17단계: 취소 확인 기록과 실제 잔고/미체결의 보수적 대조 (읽기 전용).

실제 취소확인 행의 수량 의미가 검증되지 않았으므로 승인 증빙은 생성하지 않는다.
주문 API, 상태 저장 API를 호출하지 않는다.
"""
from etf_cancel_history_step15 import build_cancel_proof

ETF_CODES = frozenset(('069500', '114800'))


def _order_no(value):
    value = str(value or '').strip()
    if not value.isdigit() or len(value) > 7:
        raise ValueError('주문번호 불명확')
    return value.zfill(7)


def _qty(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('수량 불명확')
    s = str(value).replace(',', '').strip()
    if not s.isdigit():
        raise ValueError('수량 불명확')
    return int(s)


def assess_cancel_evidence(rows, unfilled_orders, *, original_order_no, code,
                           actual_qty, expected_qty):
    """조회 스냅샷을 판정하되 항상 proof_approved=False.

    rows=None 또는 unfilled_orders=None 은 API 조회 실패. 빈 리스트는 조회 성공.
    expected_qty는 취소 요청 전 저장한 실제 보유수량이다.
    """
    result = {'status': 'CANCEL_UNVERIFIED', 'proof_approved': False,
              'candidate_found': False, 'account_matches': False,
              'unfilled_clear': False}
    if code not in ETF_CODES or rows is None or unfilled_orders is None:
        return result
    if (not isinstance(rows, list) or not isinstance(unfilled_orders, list)
            or any(not isinstance(x, dict) for x in rows + unfilled_orders)):
        return result
    try:
        target = _order_no(original_order_no)
        actual = _qty(actual_qty)
        expected = _qty(expected_qty)
        if expected <= 0:
            return result
        result['account_matches'] = actual == expected
        for item in unfilled_orders:
            item_code = str(item.get('stk_cd', '')).removeprefix('A').strip()
            if item_code not in ETF_CODES:
                continue
            if _qty(item.get('oso_qty')) > 0:
                # 다른 ETF 주문까지 남아 있으면 정합성 확인 보류.
                return result
        result['unfilled_clear'] = True
        candidate = build_cancel_proof(rows, original_order_no=target,
                                       code=code, complete_history=True)
        result['candidate_found'] = candidate is not None
        if candidate and result['account_matches']:
            result['status'] = 'CANDIDATE_REQUIRES_LIVE_SEMANTICS'
        elif not result['account_matches']:
            result['status'] = 'HOLDING_CHANGED_RECONCILE_REQUIRED'
        return result
    except (ValueError, TypeError):
        return result
