"""16단계: 실제 kt00007 취소 행의 비식별 구조만 진단. 주문/상태 변경 없음."""
import argparse
from datetime import datetime

from etf_cancel_history_step15 import build_cancel_proof

ETF_CODES = {'069500', '114800'}


def inspect_cancel_rows(rows):
    if rows is None or not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        return {'status': 'QUERY_UNVERIFIED'}
    etf = [r for r in rows if str(r.get('stk_cd', '')).removeprefix('A').strip() in ETF_CODES]
    cancellations = [r for r in etf if str(r.get('mdfy_cncl', '')).strip() == '취소확인']
    # 주문번호, 원주문번호, 계좌, 수량, 가격, 시간 등 실제 값은 절대 반환하지 않음.
    return {
        'status': 'READ_ONLY_OK',
        'etf_rows': len(etf),
        'cancel_confirmation_rows': len(cancellations),
        'cancel_field_presence': {key: sum(key in r and r[key] is not None for r in cancellations)
                                  for key in ('ord_no', 'ori_ord', 'stk_cd', 'io_tp_nm',
                                              'ord_qty', 'cnfm_qty', 'cntr_qty', 'ord_remnq',
                                              'mdfy_cncl')},
        'cancel_side_categories': sorted({str(r.get('io_tp_nm', '')).strip() for r in cancellations}),
        'cancel_exchange_categories': sorted({str(r.get('dmst_stex_tp', '')).strip() for r in cancellations}),
        'proof_approved': False,
    }


def inspect_candidate(rows, *, original_order_no, code):
    """후보 존재 여부만 반환. 실거래 취소 승인 불가."""
    if rows is None:
        return {'status': 'QUERY_UNVERIFIED', 'proof_approved': False}
    candidate = build_cancel_proof(rows, original_order_no=original_order_no,
                                   code=code, complete_history=True)
    return {'status': 'CANDIDATE_UNVERIFIED' if candidate else 'NO_VERIFIED_CANDIDATE',
            'proof_approved': False}


def main():
    parser = argparse.ArgumentParser(description='kt00007 ETF 취소 행 비식별 진단 (읽기 전용)')
    parser.add_argument('--date', default=datetime.now().strftime('%Y%m%d'))
    args = parser.parse_args()
    try:
        if len(args.date) != 8 or datetime.strptime(args.date, '%Y%m%d').strftime('%Y%m%d') != args.date:
            raise ValueError
    except ValueError:
        parser.error('날짜는 YYYYMMDD 형식이어야 합니다')
    from b_auth import get_token
    from c2_program import get_etf_order_history_rows
    token = get_token()
    rows = get_etf_order_history_rows(token, args.date, query_type='1')
    result = inspect_cancel_rows(rows)
    for key, value in result.items():
        print(f'{key}: {value}')
    if result['status'] != 'READ_ONLY_OK':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
