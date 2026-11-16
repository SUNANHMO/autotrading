"""외부 키움 호출 없는 조회 안전성 테스트."""
from unittest.mock import patch
import c2_program as m

calls = []
def pages(token, params, cont, key):
    calls.append((cont, key))
    if cont == 'N':
        return ({'return_code': 0, 'acnt_ord_cntr_prps_dtl':[{'ord_no':'111'}]}, 'Y', 'next')
    return ({'return_code': '0', 'acnt_ord_cntr_prps_dtl':[{'ord_no':'222'}]}, 'N', '')
with patch.object(m, 'fn_kt00007', side_effect=pages):
    assert [x['ord_no'] for x in m.get_etf_order_history_rows('token','20261116')] == ['111','222']
assert calls == [('N',''),('Y','next')]
with patch.object(m, 'fn_kt00007', return_value=({'return_code': 0, 'acnt_ord_cntr_prps_dtl':[]},'Y','same')):
    assert m.get_etf_order_history_rows('token','20261116') is None
with patch.object(m, 'fn_kt00007', return_value=({'return_code': 0},'N','')):
    assert m.get_etf_order_history_rows('token','20261116') is None
with patch.object(m, 'fn_kt00007', return_value=({'return_code': -1, 'acnt_ord_cntr_prps_dtl':[]},'N','')):
    assert m.get_etf_order_history_rows('token','20261116') is None
assert m.get_etf_order_history_rows('token','bad') is None
assert m.get_etf_order_history_rows('token','20261301') is None
print('6 tests passed')
with patch.object(m, 'fn_kt00007', return_value=({'return_code': 0, 'acnt_ord_cntr_prps_dtl': []}, 'N', '')) as api:
    assert m.get_etf_order_history_rows('token', '20261116') == []
    assert api.call_args.args[1]['qry_tp'] == '1'
assert m.get_etf_order_history_rows('token', '20261116', query_type='0') is None
print('2 additional tests passed')
