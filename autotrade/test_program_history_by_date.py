"""키움 ka90008 삼성전자 날짜별 프로그램 순매수 이력 조회 전용 (주문 없음).
실행: python test_program_history_by_date.py YYYYMMDD
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
import requests
from b_auth import get_token


def main():
    now = datetime.now()
    date = sys.argv[1] if len(sys.argv) > 1 else now.strftime("%Y%m%d")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError:
        print("사용법: python test_program_history_by_date.py YYYYMMDD")
        return
    print(f"[TEST] 조회일={date} / 005930 / ka90008 / 주문 없음")
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
    params = {'amt_qty_tp': '1', 'stk_cd': '005930', 'date': date}
    records = []
    seen_keys = set()
    try:
        for page in range(1, 101):
            if page > 1:
                time.sleep(0.5)
            for attempt in range(5):
                response = requests.post(url, headers=headers, json=params, timeout=20)
                if response.status_code != 429:
                    break
                wait = 5 * (attempt + 1)
                print(f'[RATE LIMIT] 429 / {wait}초 대기 후 {page}페이지 재시도 ({attempt + 1}/5)')
                time.sleep(wait)
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
    out = Path(f'program_history_{date}.json')
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n[RESULT] 총 {len(records)}건 / 저장: {out.resolve()}')
    # 현재 ETF 가상 전략과 동일한 고점·저점 대비 200억 방향 전환 계산.
    # 원본 조회 데이터는 보존하며, 거래 종료 후 데이터는 전략 분석에서 제외.
    def amount(value):
        value = str(value).strip()
        if value.startswith('--'):
            return -int(value[2:])
        return int(value.lstrip('+'))

    position, high, low = 'NONE', None, None
    signals = []
    for row in records:
        tm = str(row.get('tm', '')).zfill(6)
        if tm > '152000':
            break
        try:
            net = amount(row['prm_netprps_amt'])
            buy = amount(row['prm_buy_amt'])
            sell = amount(row['prm_sell_amt'])
        except (KeyError, ValueError, TypeError) as exc:
            print(f'[FAIL] 수급값 해석 실패: {tm}: {exc}')
            return
        if net != buy - sell:
            print(f'[FAIL] 수급값 불일치: {tm}: {net} != {buy} - {sell}')
            return
        if high is None:
            high = low = net
            continue
        old = position
        if position == 'NONE':
            high, low = max(high, net), min(low, net)
            if high - net >= 20000:
                position = 'INVERSE'
            elif net - low >= 20000:
                position = 'KODEX200'
        elif position == 'KODEX200':
            high = max(high, net)
            if high - net >= 20000:
                position = 'INVERSE'
        else:
            low = min(low, net)
            if net - low >= 20000:
                position = 'KODEX200'
        if position != old:
            high = low = net
            signals.append({'time': tm, 'position': position, 'net_amount_million': net})

    print(f'\n[ETF 가상 포지션 전환] 총 {len(signals)}회 / 15:20 이전')
    for signal in signals:
        tm = signal['time']
        formatted = f'{tm[:2]}:{tm[2:4]}:{tm[4:6]}'
        print(f"  {formatted}  {signal['position']:<8}  순매수 {signal['net_amount_million']/100:,.2f}억")
    signals_out = Path(f'etf_position_signals_{date}.json')
    signals_out.write_text(json.dumps(signals, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[포지션 기록 저장] {signals_out.resolve()}')

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
