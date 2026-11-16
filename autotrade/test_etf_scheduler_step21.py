from etf_scheduler_diagnostic_step21 import evaluate_step21


def run():
    checks = 0
    def check(**kwargs):
        nonlocal checks
        r = evaluate_step21(**kwargs)
        assert r['can_submit_order'] is False
        checks += 1
        return r
    base = dict(virtual_position='KODEX200', holdings=[{'stk_cd':'A069500','rmnd_qty':'34'}],
                unfilled_orders=[], now_time='140000', account_verified=True,
                orders_verified=True, lead_blocked=False, cancel_pending=False,
                closing_order_pending=False)
    assert check(**base)['action'] == 'ALIGNED_HOLD'
    assert check(**{**base,'account_verified':False})['status'] == 'VERIFY_REQUIRED'
    assert check(**{**base,'orders_verified':False})['status'] == 'VERIFY_REQUIRED'
    assert check(**{**base,'lead_blocked':True})['action'] == 'LEAD_PRIORITY_WAIT'
    assert check(**{**base,'cancel_pending':True})['action'] == 'VERIFY_PENDING_CANCEL'
    sell={'stk_cd':'A069500','oso_qty':'34','ord_no':'0187061','io_tp_nm':'-매도'}
    assert check(**{**base,'unfilled_orders':[sell]})['action'] == 'REVIEW_STALE_SELL_CANCEL'
    assert check(**{**base,'virtual_position':'INVERSE','unfilled_orders':[sell]})['action'] == 'VERIFY_EXISTING_ORDER'
    assert check(**{**base,'now_time':'152100','unfilled_orders':[sell]})['action'] == 'CANCEL_PENDING_ORDERS_THEN_VERIFY'
    assert check(**{**base,'now_time':'152100'})['action'] == 'VERIFY_CANCELLATION_OR_NO_CANCEL_NEEDED'
    assert check(**{**base,'now_time':'152100','cancel_pending':True})['action'] == 'VERIFY_PENDING_CANCEL'
    assert check(**{**base,'now_time':'152100','closing_order_pending':True})['action'] == 'VERIFY_EXISTING_CLOSING_ORDER'
    assert check(**{**base,'now_time':'bad'})['status'] == 'VERIFY_REQUIRED'
    assert check(**{**base,'unfilled_orders':None})['can_submit_order'] is False
    assert check(**{**base,'holdings':None})['can_submit_order'] is False
    print(f'{checks} tests passed')

if __name__ == '__main__': run()
