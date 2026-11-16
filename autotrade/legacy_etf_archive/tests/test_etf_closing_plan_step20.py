import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent.parent))

from etf_closing_plan_step20 import plan_etf_closing

BASE = dict(now_time='152100', holdings=[{'stk_cd':'A069500','rmnd_qty':'34'}],
            unfilled_orders=[], account_verified=True, orders_verified=True,
            cancel_proof_verified=True)

def check(expected, **changes):
    data = dict(BASE, **changes)
    got = plan_etf_closing(**data)
    assert got['action'] == expected, got
    assert got['can_submit_order'] is False


def main():
    cases = [
        ('WAIT_FOR_1520', {'now_time':'151959'}),
        ('VERIFY_ACCOUNT_AND_ORDERS', {'account_verified':False}),
        ('VERIFY_ACCOUNT_AND_ORDERS', {'orders_verified':False}),
        ('VERIFY_PENDING_CANCEL', {'cancel_pending':True}),
        ('VERIFY_CANCELLATION_OR_NO_CANCEL_NEEDED', {'cancel_proof_verified':False}),
        ('REVIEW_MARKET_SELL_ACTUAL_QTY', {}),
        ('CLOSING_ZERO_BALANCE_CONFIRMED', {'holdings':[]}),
        ('VERIFY_AFTER_CLOSE_BALANCE', {'now_time':'153000'}),
        ('VERIFY_EXISTING_CLOSING_ORDER', {'closing_order_pending':True}),
        ('VERIFY_EXISTING_CLOSING_ORDER', {'closing_order_verified':True}),
        ('CANCEL_PENDING_ORDERS_THEN_VERIFY', {'unfilled_orders':[{'stk_cd':'069500','oso_qty':'34','ord_no':'1234567','io_tp_nm':'-매도'}]}),
        ('VERIFY_INPUTS', {'holdings':None}),
        ('VERIFY_INPUTS', {'holdings':[{'stk_cd':'069500','rmnd_qty':'34'}, {'stk_cd':'069500','rmnd_qty':'34'}]}),
        ('VERIFY_INPUTS', {'holdings':[{'stk_cd':'069500','rmnd_qty':'34'}, {'stk_cd':'114800','rmnd_qty':'2'}]}),
        ('VERIFY_INPUTS', {'unfilled_orders':[{'stk_cd':'069500','oso_qty':'1','ord_no':'x','io_tp_nm':'-매도'}]}),
        ('VERIFY_INPUTS', {'unfilled_orders':[{'stk_cd':'069500','oso_qty':'1','ord_no':'123','io_tp_nm':'?'}]}),
        ('VERIFY_INPUTS', {'now_time':'256100'}),
        ('VERIFY_INPUTS', {'cancel_pending':'false'}),
        ('VERIFY_INPUTS', {'unfilled_orders':[{'stk_cd':'069500','oso_qty':'1','ord_no':'123','io_tp_nm':'-매도'}, {'stk_cd':'069500','oso_qty':'1','ord_no':'0000123','io_tp_nm':'-매도'}]}),
        ('VERIFY_INPUTS', {'unfilled_orders':[{'stk_cd':'005930','oso_qty':'1','ord_no':'123','io_tp_nm':'-매도'}]}),
    ]
    for expected, kwargs in cases:
        check(expected, **kwargs)
    print(f'{len(cases)} tests passed')

if __name__ == '__main__':
    main()
