"""15단계: kt00007 읽기 전용 취소 증빙 후보 판정. 주문/상태 변경 없음.

보수적으로 전량 미체결 취소만 승인한다. 부분체결/부분취소/중복 행은 보류.
"""
from datetime import datetime
from etf_cancel_proof import validate_cancel_proof

ETF_CODES = {'069500', '114800'}


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('수량 누락')
    raw = str(value).strip().replace(',', '')
    if not raw or not raw.isdigit():
        raise ValueError('수량 형식 불명확')
    return int(raw)


def _order(value):
    raw = str(value or '').strip()
    if not raw.isdigit() or len(raw) > 7:
        raise ValueError('주문번호 형식 불명확')
    return raw.zfill(7)


def build_cancel_proof(rows, *, original_order_no, code, complete_history=False):
    """성공 시 검증 가능한 dict, 불명확하면 None. 원주문 전량 미체결 취소만 지원.

    취소확인 행의 cnfm_qty가 원주문 전체 수량과 같고 체결이 0인 경우만
    보수적으로 인정. API에서 실제 취소확인 행의 수량 의미 확인 전에는
    실거래 자동 연결 금지.
    """
    if complete_history is not True or not isinstance(rows, list):
        return None
    if not isinstance(code, str) or code not in ETF_CODES:
        return None
    try:
        order_no = _order(original_order_no)
        originals, cancellations = [], []
        for row in rows:
            if not isinstance(row, dict):
                return None
            row_code = str(row.get('stk_cd', '')).removeprefix('A').strip()
            if row_code != code:
                continue
            row_no = _order(row.get('ord_no'))
            parent = _order(row.get('ori_ord'))
            if row_no == order_no and parent == '0000000':
                originals.append(row)
            if parent == order_no and row_no != order_no and row.get('mdfy_cncl') == '취소확인':
                cancellations.append(row)
        if len(originals) != 1 or len(cancellations) != 1:
            return None
        original, cancel = originals[0], cancellations[0]
        qty = _number(original.get('ord_qty'))
        if qty <= 0 or _number(original.get('cntr_qty')) != 0:
            return None
        if original.get('io_tp_nm') != '현금매도' or cancel.get('io_tp_nm') != '현금매도':
            return None
        if (_number(cancel.get('cnfm_qty')) != qty or
                _number(cancel.get('cntr_qty')) != 0 or
                _number(cancel.get('ord_remnq')) != 0):
            return None
        # 확인수량과 취소확인만으로 실제 거래소 취소가 확정된다는 보장이
        # 아직 없으므로 운영 증빙 승인 플래그를 자동으로 세우지 않는다.
        return {'original_order_no': order_no, 'code': code,
                'cancel_status': 'CANDIDATE', 'remaining_qty': 0,
                'source_verified': False, 'complete_history': True,
                'confirmed_qty': qty}
    except (ValueError, TypeError):
        return None


def inspect_cancel_history(token, *, original_order_no, code, order_date=None):
    """실제 계좌 조회. 증빙 후보만 반환하고 승인/주문/상태변경하지 않음."""
    from c2_program import get_etf_order_history_rows
    date = order_date or datetime.now().strftime('%Y%m%d')
    rows = get_etf_order_history_rows(token, date, query_type='1')
    candidate = build_cancel_proof(rows, original_order_no=original_order_no,
                                   code=code, complete_history=(rows is not None))
    return {'status': 'CANDIDATE_UNVERIFIED' if candidate else 'NO_VERIFIED_CANDIDATE',
            'candidate': candidate,
            'approved': validate_cancel_proof(candidate, original_order_no=original_order_no, code=code)}
