"""14단계: kt00007 읽기 전용 응답 구조 확인. 주문/취소 API 호출 없음."""
import argparse
from datetime import datetime
from c2_program import get_etf_order_history_rows

ETF_CODES = ('069500', '114800')


def inspect_rows(rows):
    """민감한 값 대신 필드명, ETF 관련 코드, 비식별 상태 문자열만 표시."""
    if rows is None:
        return {'status': 'QUERY_UNVERIFIED'}
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        return {'status': 'INVALID_ROWS'}
    fields = sorted({str(k) for row in rows for k in row})
    # 원주문번호/계좌번호/가격/수량 등 값은 출력하지 않는다.
    etf_rows = [r for r in rows if any(
        str(r.get(k, '')).removeprefix('A').strip() in ETF_CODES
        for k in ('stk_cd', 'stk_code', 'code'))]
    status_keys = [k for k in fields if any(x in k.lower() for x in
                   ('io_tp', 'ord_st', 'cntr_st', 'trde_tp', 'ord_gb'))]
    # 상태값도 주문번호 등이 들어갈 수 있으므로 길이와 개수만 기록.
    return {'status': 'READ_ONLY_OK', 'total_rows': len(rows),
            'etf_rows': len(etf_rows), 'field_names': fields,
            'candidate_status_field_names': status_keys,
            'cancel_proof_created': False}


def main():
    p = argparse.ArgumentParser(description='ETF 주문 내역 응답 키만 확인(주문 없음)')
    p.add_argument('--date', default=datetime.now().strftime('%Y%m%d'))
    p.add_argument('--query-type', default='1', choices=('1', '2', '3', '4'))
    args = p.parse_args()
    if len(args.date) != 8 or not args.date.isdigit():
        p.error('날짜는 YYYYMMDD 형식이어야 합니다')
    from b_auth import get_token
    token = get_token()
    rows = get_etf_order_history_rows(token, args.date, query_type=args.query_type)
    result = inspect_rows(rows)
    for key, value in result.items():
        print(f'{key}: {value}')
    if result['status'] != 'READ_ONLY_OK':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
