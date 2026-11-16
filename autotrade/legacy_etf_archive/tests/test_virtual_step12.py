import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent.parent))

from etf_virtual_strategy import replay_virtual_strategy, plan_virtual_alignment

def row(tm, net):
    return {'tm': tm, 'prm_netprps_amt': str(net), 'prm_buy_amt': str(max(net, 0)), 'prm_sell_amt': str(max(-net, 0))}

history = [row(f'09{i:02d}00', n) for i, n in enumerate([10000,30000,10000,-100000,-80000,-70000,-90000])]
result = replay_virtual_strategy(history, now_time='091000')
assert [x['to'] for x in result['transitions']] == ['KODEX200','INVERSE','KODEX200','INVERSE']
assert result['position'] == 'INVERSE'
order = [{'code': '069500', 'side_raw': {'io_tp_nm': '-매도'}}]
common = dict(account_position='KODEX200', account_qty=34, unfilled_orders=order, now_time='091000', account_verified=True, orders_verified=True)
assert plan_virtual_alignment(virtual_position='INVERSE', **common) == 'WAIT_EXISTING_ORDER'
assert plan_virtual_alignment(virtual_position='KODEX200', **common) == 'CANCEL_STALE_SELL'
assert plan_virtual_alignment(virtual_position='KODEX200', **{**common, 'now_time':'152000'}) == 'CLOSING_CANCEL_THEN_VERIFY'
assert plan_virtual_alignment(virtual_position='KODEX200', **{**common, 'unfilled_orders':[],'now_time':'152100'}) == 'CLOSING_SELL_IF_HELD'
assert plan_virtual_alignment(virtual_position='KODEX200', **{**common, 'unfilled_orders':[],'account_qty':0,'account_position':'NONE','now_time':'152100'}) == 'CLOSING_VERIFY_ZERO'
assert plan_virtual_alignment(virtual_position='KODEX200', **{**common, 'unfilled_orders':[{'code':'069500','side_raw':{'io_tp_nm':'+매수'}}]}) == 'VERIFY_ORDER_SIDE'
print('6 tests passed')
