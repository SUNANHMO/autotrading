from etf_partial_reconcile_step19 import reconcile_etf_snapshot

BASE = dict(virtual_position='KODEX200', holdings=[{'stk_cd':'A069500','rmnd_qty':'34'}],
            unfilled_orders=[], now_time='130000', account_verified=True, orders_verified=True)

def check(expected, **updates):
    args = dict(BASE); args.update(updates)
    result = reconcile_etf_snapshot(**args)
    assert result['action'] == expected, result
    assert result['can_submit_order'] is False
    assert result['partial_fill_confirmed'] is False
    return result


def run():
    count=0
    check('ALIGNED_HOLD'); count+=1
    check('REVIEW_STALE_SELL_CANCEL', unfilled_orders=[{'stk_cd':'069500','ord_no':'0187061','oso_qty':'34','io_tp_nm':'-매도'}]); count+=1
    check('REVIEW_STALE_SELL_CANCEL', unfilled_orders=[{'stk_cd':'069500','ord_no':'0187061','oso_qty':'12','io_tp_nm':'-매도'}]); count+=1
    check('VERIFY_EXISTING_ORDER', virtual_position='INVERSE', unfilled_orders=[{'stk_cd':'069500','ord_no':'0187061','oso_qty':'34','io_tp_nm':'-매도'}]); count+=1
    check('VERIFY_PENDING_CANCEL', cancel_pending=True); count+=1
    check('LEAD_PRIORITY_WAIT', lead_blocked=True); count+=1
    check('CLOSING_SELL_IF_HELD', now_time='152000'); count+=1
    check('CLOSING_CANCEL_THEN_VERIFY', now_time='152000', unfilled_orders=[{'stk_cd':'069500','ord_no':'123','oso_qty':'1','io_tp_nm':'-매도'}]); count+=1
    check('ALIGNED_FLAT', virtual_position='NONE', holdings=[]); count+=1
    check('REVIEW_INITIAL_BUY', holdings=[]); count+=1
    check('REVIEW_SWITCH_SELL', virtual_position='INVERSE'); count+=1
    for changes in [
        {'account_verified':False}, {'orders_verified':False}, {'holdings':None},
        {'unfilled_orders':None}, {'holdings':[{'stk_cd':'069500','rmnd_qty':'-1'}]},
        {'holdings':[{'stk_cd':'069500','rmnd_qty':'1'},{'stk_cd':'114800','rmnd_qty':'1'}]},
        {'holdings':[{'stk_cd':'069500','rmnd_qty':'1'},{'stk_cd':'069500','rmnd_qty':'1'}]},
        {'unfilled_orders':[{'stk_cd':'069500','ord_no':'abc','oso_qty':'1','io_tp_nm':'-매도'}]},
        {'unfilled_orders':[{'stk_cd':'069500','ord_no':'123','oso_qty':'1','io_tp_nm':'?'}]},
        {'unfilled_orders':[{'stk_cd':'114800','ord_no':'123','oso_qty':'1','io_tp_nm':'-매도'}]},
        {'unfilled_orders':[{'stk_cd':'069500','ord_no':'123','oso_qty':'1','io_tp_nm':'-매도'}, {'stk_cd':'069500','ord_no':'0000123','oso_qty':'1','io_tp_nm':'-매도'}]},
        {'unfilled_orders':[{'stk_cd':'000001','ord_no':'123','oso_qty':'1','io_tp_nm':'-매도'}]},
        {'unfilled_orders':[{'stk_cd':'069500','ord_no':'123','oso_qty':True,'io_tp_nm':'-매도'}]},
        {'now_time':'999999'},
    ]:
        check('VERIFY_ACCOUNT_AND_ORDERS', **changes); count+=1
    print(f'{count} tests passed')

if __name__=='__main__': run()
