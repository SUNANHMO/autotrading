import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent.parent))

from unittest.mock import patch
import etf_cancel_reconcile as m

order = {'stk_cd':'069500','ord_no':'0187061','io_tp_nm':'-매도','oso_qty':'34'}
base = dict(virtual_position='KODEX200', account_position='KODEX200',
            account_qty=34, original_order_no='0187061')
with patch.object(m, 'get_etf_unfilled_orders', return_value=[order]), patch.object(m, 'etf_cancel_order', return_value={'return_code':0}) as cancel:
    result = m.request_stale_sell_cancel('token', **base)
    assert result['status'] == 'CANCEL_REQUESTED'
    cancel.assert_called_once_with('token', '069500', '0187061')
with patch.object(m, 'get_etf_unfilled_orders', return_value=[order]), patch.object(m, 'etf_cancel_order') as cancel:
    assert m.request_stale_sell_cancel('token', **{**base,'virtual_position':'INVERSE'})['status'] == 'BLOCKED'
    cancel.assert_not_called()
with patch.object(m, 'get_etf_unfilled_orders', return_value=[{**order,'io_tp_nm':'+매수'}]), patch.object(m, 'etf_cancel_order') as cancel:
    assert m.request_stale_sell_cancel('token', **base)['status'] == 'BLOCKED'
    cancel.assert_not_called()
with patch.object(m, 'get_etf_unfilled_orders', return_value=[order,order]), patch.object(m, 'etf_cancel_order') as cancel:
    assert m.request_stale_sell_cancel('token', **base)['status'] == 'BLOCKED'
    cancel.assert_not_called()
assert m.verify_cancel_complete([order], original_order_no='0187061') == 'STILL_OPEN'
assert m.verify_cancel_complete([], original_order_no='0187061') == 'NO_LONGER_UNFILLED_VERIFY_BALANCE_AND_FILLS'
assert m.verify_cancel_complete(None, original_order_no='0187061') == 'VERIFY_FAILED'
print('7 tests passed')
