"""삼성전자 당일 프로그램 순매수 과거 조회 확인용. 주문 실행 없음.
실행: python test_program_history.py
"""
from datetime import datetime
from b_auth import get_token
from h_schedule import check_program_history


def main():
    print(f'[TEST] 시작 {datetime.now():%Y-%m-%d %H:%M:%S}')
    print('[TEST] 삼성전자(005930) ka90008 과거 프로그램 수급 조회; 주문 없음')
    token = get_token()
    if not token:
        print('[FAIL] 토큰 발급 실패')
        return
    rows = check_program_history(token, '005930')
    if rows is None:
        print('[FAIL] 과거 조회 또는 기존 함수의 검증 실패. 위 오류를 전달해 주세요.')
        return
    print(f'[OK] 총 {len(rows)}건')
    print('[처음 10건]')
    for row in rows[:10]:
        print('  ', row.get('tm'), '순매수=', row.get('prm_netprps_amt'),
              '매수=', row.get('prm_buy_amt'), '매도=', row.get('prm_sell_amt'))
    print('[마지막 10건]')
    for row in rows[-10:]:
        print('  ', row.get('tm'), '순매수=', row.get('prm_netprps_amt'),
              '매수=', row.get('prm_buy_amt'), '매도=', row.get('prm_sell_amt'))
    print('[OK] 전체 원본 기록은 program_history.json에 저장됨')


if __name__ == '__main__':
    main()
