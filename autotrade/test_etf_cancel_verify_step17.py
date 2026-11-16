from etf_cancel_verify_step17 import assess_cancel_evidence

ORIGINAL = {'ord_no':'0123456','ori_ord':'0000000','stk_cd':'A069500','ord_qty':'0000000034','cntr_qty':'0000000000','io_tp_nm':'현금매도'}
CANCEL = {'ord_no':'0123457','ori_ord':'0123456','stk_cd':'A069500','mdfy_cncl':'취소확인','cnfm_qty':'0000000034','cntr_qty':'0000000000','ord_remnq':'0000000000','io_tp_nm':'현금매도'}


def run(rows=None, orders=None, actual=34, expected=34, code='069500', no='0123456'):
    return assess_cancel_evidence([ORIGINAL, CANCEL] if rows is None else rows,
                                  [] if orders is None else orders,
                                  original_order_no=no, code=code,
                                  actual_qty=actual, expected_qty=expected)


def main():
    cases = [
        (run(), 'CANDIDATE_REQUIRES_LIVE_SEMANTICS', True),
        (run(rows=[]), 'CANCEL_UNVERIFIED', False),
        (run(rows=[ORIGINAL]), 'CANCEL_UNVERIFIED', False),
        (run(orders=[{'stk_cd':'A069500','oso_qty':'34'}]), 'CANCEL_UNVERIFIED', False),
        (run(orders=[{'stk_cd':'A114800','oso_qty':'1'}]), 'CANCEL_UNVERIFIED', False),
        (run(actual=33), 'HOLDING_CHANGED_RECONCILE_REQUIRED', True),
        (run(expected=35), 'HOLDING_CHANGED_RECONCILE_REQUIRED', True),
        (run(code='000000'), 'CANCEL_UNVERIFIED', False),
        (run(no='9999999'), 'CANCEL_UNVERIFIED', False),
        (run(rows='bad'), 'CANCEL_UNVERIFIED', False),
        (run(orders=[{'stk_cd':'A069500'}]), 'CANCEL_UNVERIFIED', False),
        (run(actual=-1), 'CANCEL_UNVERIFIED', False),
    ]
    for i, (out, status, candidate) in enumerate(cases, 1):
        assert out['status'] == status, (i, out)
        assert out['candidate_found'] is candidate, (i, out)
        assert out['proof_approved'] is False, (i, out)
    assert assess_cancel_evidence(None, [], original_order_no='0123456', code='069500', actual_qty=34, expected_qty=34)['proof_approved'] is False
    assert assess_cancel_evidence([], None, original_order_no='0123456', code='069500', actual_qty=34, expected_qty=34)['proof_approved'] is False
    print('14 tests passed')

if __name__ == '__main__':
    main()
