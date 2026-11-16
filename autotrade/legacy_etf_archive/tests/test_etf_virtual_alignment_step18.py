import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent.parent))

from etf_virtual_alignment_step18 import plan_virtual_account_alignment as plan


def check(action, **updates):
    args = dict(virtual_position='KODEX200', account_position='KODEX200',
                account_qty=34, unfilled_orders=[], now_time='110000',
                account_verified=True, orders_verified=True)
    args.update(updates)
    result = plan(**args)
    assert result['action'] == action, (action, result)
    assert result['can_submit_order'] is False
    assert result['virtual_position'] == args['virtual_position']
    return result


def main():
    sell = {'stk_cd': 'A069500', 'io_tp_nm': '-매도', 'oso_qty': '34'}
    buy = {'stk_cd': 'A114800', 'io_tp_nm': '+매수', 'oso_qty': '12'}
    check('ALIGNED_HOLD')
    check('REVIEW_STALE_SELL_CANCEL', unfilled_orders=[sell])
    check('VERIFY_EXISTING_ORDER', virtual_position='INVERSE', unfilled_orders=[sell])
    check('VERIFY_EXISTING_ORDER', virtual_position='INVERSE', unfilled_orders=[buy])
    check('VERIFY_EXISTING_ORDER', unfilled_orders=[sell, sell])
    check('REVIEW_SWITCH_SELL', virtual_position='INVERSE')
    check('REVIEW_INITIAL_BUY', virtual_position='INVERSE', account_position='NONE', account_qty=0)
    check('ALIGNED_FLAT', virtual_position='NONE', account_position='NONE', account_qty=0)
    check('REVIEW_EXIT_TO_FLAT', virtual_position='NONE')
    check('VERIFY_PENDING_CANCEL', unfilled_orders=[sell], cancel_pending=True)
    check('LEAD_PRIORITY_WAIT', unfilled_orders=[sell], lead_blocked=True)
    check('CLOSING_CANCEL_THEN_VERIFY', unfilled_orders=[sell], now_time='152000')
    check('CLOSING_SELL_IF_HELD', now_time='152000')
    check('CLOSING_VERIFY_ZERO', account_position='NONE', account_qty=0, now_time='153100')
    check('OUTSIDE_ENTRY_WINDOW', now_time='085959')
    check('VERIFY_ACCOUNT_AND_ORDERS', account_verified=False)
    check('VERIFY_ACCOUNT_AND_ORDERS', orders_verified=False)
    check('VERIFY_INPUTS', account_position='NONE')
    check('VERIFY_INPUTS', account_qty=True)
    check('VERIFY_INPUTS', unfilled_orders=[{'stk_cd':'A069500','oso_qty':'34'}])
    check('VERIFY_INPUTS', unfilled_orders=[{'stk_cd':'A069500','io_tp_nm':'-매도','oso_qty':'bad'}])
    check('VERIFY_INPUTS', unfilled_orders=[{'stk_cd':'A005930','io_tp_nm':'-매도','oso_qty':'1'}])
    check('VERIFY_INPUTS', now_time='256100')
    check('VERIFY_INPUTS', cancel_pending='yes')
    check('VERIFY_INPUTS', unfilled_orders=None)
    print('25 tests passed')


if __name__ == '__main__':
    main()
