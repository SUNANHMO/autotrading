from etf_history_inspect_step14 import inspect_rows
assert inspect_rows(None)['status'] == 'QUERY_UNVERIFIED'
assert inspect_rows([None])['status'] == 'INVALID_ROWS'
r = inspect_rows([{'stk_cd': 'A069500', 'ord_no': 'SECRET', 'io_tp_nm': '매도'}, {'stk_cd': '005930'}])
assert r['status'] == 'READ_ONLY_OK'
assert r['total_rows'] == 2 and r['etf_rows'] == 1
assert 'ord_no' in r['field_names']
assert 'SECRET' not in str(r)
assert r['cancel_proof_created'] is False
assert inspect_rows([])['etf_rows'] == 0
print('6 tests passed')
