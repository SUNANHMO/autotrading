"""키움 ka90008 삼성전자 당일 프로그램 순매수 이력 조회 전용 (주문 없음).
실행: python test_program_history_fixed.py
"""
import json
from datetime import datetime
from pathlib import Path
import requests
from b_auth import get_token


def main():
    now = datetime.now()
    print(f'[TEST] {now:%Y-%m-%d %H:%M:%S} / 005930 / ka90008 / 주문 없음')
    token = get_token()
    if not token:
        print('[FAIL] 토큰 발급 실패')
        return
    url = 'https://api.kiwoom.com/api/dostk/mrkcond'
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': 'N', 'next-key': '', 'api-id': 'ka90008',
    }
    params = {'amt_qty_tp': '1', 'stk_cd': '005930', 'date': now.strftime('%Y%m%d')}
    records = []
    seen_keys = set()
    try:
        for page in range(1, 101):
            response = requests.post(url, headers=headers, json=params, timeout=20)
            response.raise_for_status()
            result = response.json()
            if str(result.get('return_code')) != '0':
                print(f'[FAIL] API 오류: return_code={result.get("return_code")}, msg={result.get("return_msg")}')
                return
            rows = result.get('stk_tm_prm_trde_trnsn')
            if not isinstance(rows, list):
                print('[FAIL] 데이터 배열 없음. 응답 필드:', list(result.keys()))
                return
            records.extend(rows)
            cont = response.headers.get('cont-yn', 'N').upper()
            next_key = response.headers.get('next-key', '')
            print(f'[PAGE {page}] {len(rows)}건, 누적 {len(records)}건, 연속조회={cont}')
            if cont == 'N':
                break
            if cont != 'Y' or not next_key or next_key in seen_keys:
                print('[FAIL] 연속조회 헤더 이상')
                return
            seen_keys.add(next_key)
            headers['cont-yn'] = 'Y'
            headers['next-key'] = next_key
        else:
            print('[FAIL] 최대 100페이지 초과')
            return
    except (requests.RequestException, ValueError) as exc:
        print('[FAIL] 조회 실패:', exc)
        return

    records.sort(key=lambda x: str(x.get('tm', '')))
    out = Path('program_history_test.json')
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n[RESULT] 총 {len(records)}건 / 저장: {out.resolve()}')
    if records:
        print('[데이터 필드]', ', '.join(records[0].keys()))
        print('[최초 10건]')
        for row in records[:10]:
            print(' ', row.get('tm'), '순매수=', row.get('prm_netprps_amt'),
                  '매수=', row.get('prm_buy_amt'), '매도=', row.get('prm_sell_amt'))
        print('[마지막 10건]')
        for row in records[-10:]:
            print(' ', row.get('tm'), '순매수=', row.get('prm_netprps_amt'),
                  '매수=', row.get('prm_buy_amt'), '매도=', row.get('prm_sell_amt'))


if __name__ == '__main__':
    main()
