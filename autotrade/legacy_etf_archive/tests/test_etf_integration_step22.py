"""22단계: 17~21단계 순수 판정 모듈 회귀/연계 테스트. 실제 주문/API 호출 없음."""
import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent.parent))

from copy import deepcopy
from etf_scheduler_diagnostic_step21 import evaluate_step21
from etf_cancel_verify_step17 import assess_cancel_evidence
from etf_cancel_proof import validate_cancel_proof
from etf_closing_plan_step20 import plan_etf_closing

H = [{'stk_cd': 'A069500', 'rmnd_qty': '34'}]
SELL = {'stk_cd': 'A069500', 'oso_qty': '34', 'ord_no': '0187061', 'io_tp_nm': '-매도'}

def evaluate(**updates):
    args = dict(virtual_position='KODEX200', holdings=deepcopy(H),
                unfilled_orders=[], now_time='140000', account_verified=True,
                orders_verified=True, lead_blocked=False, cancel_pending=False,
                cancel_proof_verified=False, closing_order_pending=False)
    args.update(updates)
    original = deepcopy(args)
    result = evaluate_step21(**args)
    assert args == original, '진단 함수가 입력 스냅샷을 변경함'
    assert result['can_submit_order'] is False
    return result

def run():
    n = 0
    def expect(action, **updates):
        nonlocal n
        result = evaluate(**updates)
        assert result['action'] == action, (action, result)
        n += 1
        return result

    expect('ALIGNED_HOLD')
    expect('REVIEW_STALE_SELL_CANCEL', unfilled_orders=[SELL])
    expect('VERIFY_EXISTING_ORDER', virtual_position='INVERSE', unfilled_orders=[SELL])
    expect('ALIGNED_HOLD', virtual_position='KODEX200')
    expect('REVIEW_SWITCH_SELL', virtual_position='INVERSE')
    expect('VERIFY_PENDING_CANCEL', cancel_pending=True, unfilled_orders=[SELL])
    expect('LEAD_PRIORITY_WAIT', lead_blocked=True)
    expect('REVIEW_INITIAL_BUY', holdings=[], virtual_position='INVERSE')
    expect('ALIGNED_FLAT', holdings=[], virtual_position='NONE')
    expect('VERIFY_ACCOUNT_AND_ORDERS', account_verified=False)
    expect('VERIFY_ACCOUNT_AND_ORDERS', orders_verified=False)
    expect('VERIFY_ACCOUNT_AND_ORDERS', holdings=None)
    expect('VERIFY_ACCOUNT_AND_ORDERS', unfilled_orders=None)
    expect('VERIFY_ACCOUNT_AND_ORDERS', now_time='not-time')
    expect('VERIFY_ACCOUNT_AND_ORDERS', holdings=H + H)
    expect('VERIFY_ACCOUNT_AND_ORDERS', holdings=H + [{'stk_cd':'A114800','rmnd_qty':'1'}])
    expect('VERIFY_ACCOUNT_AND_ORDERS', unfilled_orders=[SELL, SELL])
    expect('VERIFY_ACCOUNT_AND_ORDERS', unfilled_orders=[{**SELL, 'oso_qty':'???'}])
    expect('VERIFY_ACCOUNT_AND_ORDERS', unfilled_orders=[{**SELL, 'io_tp_nm':'???'}])
    expect('VERIFY_ACCOUNT_AND_ORDERS', holdings=[{'stk_cd':'A069500','rmnd_qty':'0'}], unfilled_orders=[SELL])
    expect('CANCEL_PENDING_ORDERS_THEN_VERIFY', now_time='152000', unfilled_orders=[SELL])
    expect('VERIFY_PENDING_CANCEL', now_time='152100', cancel_pending=True, unfilled_orders=[SELL])
    expect('VERIFY_CANCELLATION_OR_NO_CANCEL_NEEDED', now_time='152100')
    expect('VERIFY_EXISTING_CLOSING_ORDER', now_time='152100', closing_order_pending=True)
    expect('VERIFY_AFTER_CLOSE_BALANCE', now_time='153001', cancel_proof_verified=True)
    expect('REVIEW_MARKET_SELL_ACTUAL_QTY', now_time='152100', cancel_proof_verified=True)
    expect('CLOSING_ZERO_BALANCE_CONFIRMED', now_time='152100', holdings=[], cancel_proof_verified=True)

    # 취소 기록이 없으면 주문 소멸과 잔고 일치만으로 취소 완료로 판정하지 않는다.
    candidate = assess_cancel_evidence([], [], original_order_no='0187061',
                                       code='069500', actual_qty=34, expected_qty=34)
    assert candidate['proof_approved'] is False and candidate['status'] == 'CANCEL_UNVERIFIED'; n += 1
    candidate = assess_cancel_evidence([], [SELL], original_order_no='0187061',
                                       code='069500', actual_qty=34, expected_qty=34)
    assert candidate['proof_approved'] is False and not candidate['unfilled_clear']; n += 1
    candidate = assess_cancel_evidence([], [], original_order_no='0187061',
                                       code='069500', actual_qty=33, expected_qty=34)
    assert candidate['proof_approved'] is False and candidate['status'] == 'HOLDING_CHANGED_RECONCILE_REQUIRED'; n += 1
    assert validate_cancel_proof(None, original_order_no='0187061', code='069500') is False; n += 1
    assert validate_cancel_proof({'source_verified':False, 'complete_history':True,
           'original_order_no':'0187061','code':'069500','cancel_status':'CONFIRMED',
           'remaining_qty':0}, original_order_no='0187061', code='069500') is False; n += 1

    # 종료 시각 이후에도 청산 주문이 남아 있으면 완료를 선언하지 않는다.
    closing = plan_etf_closing(now_time='153001', holdings=H, unfilled_orders=[],
                account_verified=True, orders_verified=True, cancel_proof_verified=True,
                closing_order_pending=True)
    assert closing['action'] == 'VERIFY_EXISTING_CLOSING_ORDER' and closing['can_submit_order'] is False; n += 1
    print(f'{n} integration tests passed')

if __name__ == '__main__':
    run()
