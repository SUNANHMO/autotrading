from etf_cancel_inspect_step16 import inspect_cancel_rows, inspect_candidate


def run():
    tests = [
        (inspect_cancel_rows(None)['status'] == 'QUERY_UNVERIFIED'),
        (inspect_cancel_rows([None])['status'] == 'QUERY_UNVERIFIED'),
        (inspect_cancel_rows([])['etf_rows'] == 0),
        (inspect_cancel_rows([{'stk_cd': 'A069500', 'mdfy_cncl': '취소확인', 'io_tp_nm': '현금매도', 'ord_no': '1234567', 'ori_ord': '7654321', 'cnfm_qty': '0000000034'}])['cancel_confirmation_rows'] == 1),
        (inspect_cancel_rows([{'stk_cd': '005930', 'mdfy_cncl': '취소확인'}])['cancel_confirmation_rows'] == 0),
        (inspect_cancel_rows([{'stk_cd': '114800', 'mdfy_cncl': '취소확인', 'io_tp_nm': '현금매수'}])['cancel_side_categories'] == ['현금매수']),
        ('1234567' not in str(inspect_cancel_rows([{'stk_cd': '069500', 'mdfy_cncl': '취소확인', 'ord_no': '1234567'}]))),
        (inspect_cancel_rows([{'stk_cd': '069500', 'mdfy_cncl': '취소확인'}])['proof_approved'] is False),
        (inspect_candidate(None, original_order_no='1234567', code='069500')['status'] == 'QUERY_UNVERIFIED'),
        (inspect_candidate([], original_order_no='1234567', code='069500')['proof_approved'] is False),
    ]
    assert all(tests), [i for i, result in enumerate(tests, 1) if not result]
    print(f'{len(tests)} tests passed')


if __name__ == '__main__':
    run()
