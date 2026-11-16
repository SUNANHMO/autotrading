"""12단계 후속: ETF 매도 미체결 취소의 검증된 요청/완료 판정.

이 모듈은 스케줄러에서 호출하지 않는다. 요청 함수 호출 시에만 실제 취소 API가 실행된다.
취소 접수와 취소 완료를 엄격히 구분하며 신규 매매/상태 파일 수정은 하지 않는다.
"""
from c2_program import get_etf_unfilled_orders
from f_order import etf_cancel_order

CODES = {'KODEX200': '069500', 'INVERSE': '114800'}


def _qty(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('미체결 수량 누락')
    text = str(value).replace(',', '').strip()
    if not text.isdigit():
        raise ValueError('미체결 수량 형식 오류')
    return int(text)


def _inspect(orders, position, order_no):
    if not isinstance(orders, list):
        raise ValueError('미체결 조회 실패')
    if position not in CODES:
        raise ValueError('ETF 방향 오류')
    if not order_no or not str(order_no).strip():
        raise ValueError('원주문번호 누락')
    if len(orders) != 1:
        raise ValueError('미체결 주문 개수 불일치: 취소 대상 단일 확인 불가')
    row = orders[0]
    if not isinstance(row, dict):
        raise ValueError('미체결 주문 형식 오류')
    code = str(row.get('stk_cd', '')).replace('A', '').strip()
    if code != CODES[position]:
        raise ValueError('미체결 종목과 실제 보유 방향 불일치')
    if str(row.get('ord_no', '')).strip() != str(order_no).strip():
        raise ValueError('미체결 원주문번호 불일치')
    side = str(row.get('io_tp_nm', ''))
    if '매도' not in side or '매수' in side:
        raise ValueError('매도 미체결임을 확인하지 못함')
    if _qty(row.get('oso_qty')) <= 0:
        raise ValueError('취소할 미체결 잔량 없음')
    return code


def request_stale_sell_cancel(token, *, virtual_position, account_position,
                              account_qty, original_order_no, closing=False):
    """검증 후 원주문 취소를 *한 번 요청*. 완료 판정은 별도 조회가 필요.

    재호출 시 중복 취소 요청 가능성이 있으므로 스케줄러 연결 전에는
    요청 중 상태 영속화와 재시작 복구를 반드시 추가해야 한다.
    """
    if not token:
        return {'status': 'BLOCKED', 'reason': '토큰 없음'}
    if type(closing) is not bool or type(account_qty) is not int or account_qty <= 0:
        return {'status': 'BLOCKED', 'reason': '잔고/마감 플래그 미검증'}
    if account_position not in CODES:
        return {'status': 'BLOCKED', 'reason': '보유 ETF 방향 미검증'}
    if not closing and virtual_position != account_position:
        return {'status': 'BLOCKED', 'reason': '가상 방향이 보유 방향과 달라 기존 매도 유지'}
    try:
        orders = get_etf_unfilled_orders(token)
        code = _inspect(orders, account_position, original_order_no)
    except (ValueError, TypeError) as exc:
        return {'status': 'BLOCKED', 'reason': str(exc)}
    response = etf_cancel_order(token, code, original_order_no)
    if not isinstance(response, dict) or str(response.get('return_code')) != '0':
        return {'status': 'UNKNOWN', 'reason': '취소 접수 결과 불명확: 재주문 금지'}
    return {'status': 'CANCEL_REQUESTED', 'reason': '접수만 확인; 미체결 재조회 및 잔고 재확인 필요',
            'original_order_no': str(original_order_no), 'code': code}


def verify_cancel_complete(orders, *, original_order_no):
    """조회에 원주문이 없는지만 확인. 잔고/체결/취소 확정까지 보증하지 않음."""
    if not isinstance(orders, list) or not original_order_no:
        return 'VERIFY_FAILED'
    for row in orders:
        if not isinstance(row, dict):
            return 'VERIFY_FAILED'
        if str(row.get('ord_no', '')).strip() == str(original_order_no).strip():
            try:
                if _qty(row.get('oso_qty')) > 0:
                    return 'STILL_OPEN'
            except ValueError:
                return 'VERIFY_FAILED'
    return 'NO_LONGER_UNFILLED_VERIFY_BALANCE_AND_FILLS'
