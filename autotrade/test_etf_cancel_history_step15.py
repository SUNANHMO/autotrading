from etf_cancel_history_step15 import build_cancel_proof, inspect_cancel_history
from etf_cancel_proof import validate_cancel_proof


def row(**kw):
    return dict(stk_cd='A069500', ord_no='0123456', ori_ord='0000000',
                ord_qty='0000000034', cntr_qty='0000000000',
                ord_remnq='0000000034', cnfm_qty='0000000000',
                io_tp_nm='현금매도', mdfy_cncl='', **kw)


def pair():
    a = row()
    b = row()
    b.update(ord_no='0123457', ori_ord='0123456', mdfy_cncl='취소확인',
             cnfm_qty='0000000034', ord_remnq='0000000000')
    return [a, b]


def check(rows, complete=True):
    return build_cancel_proof(rows, original_order_no='123456', code='069500', complete_history=complete)


def test():
    p = check(pair())
    assert p and p['cancel_status'] == 'CANDIDATE' and p['source_verified'] is False
    assert not validate_cancel_proof(p, original_order_no='123456', code='069500')
    assert check(pair(), False) is None
    assert check(None) is None
    rows = pair(); rows[0]['cntr_qty'] = '1'; assert check(rows) is None
    rows = pair(); rows[1]['cnfm_qty'] = '20'; assert check(rows) is None
    rows = pair(); rows[1]['ord_remnq'] = '1'; assert check(rows) is None
    rows = pair(); rows[1]['mdfy_cncl'] = '정정확인'; assert check(rows) is None
    rows = pair(); rows[1]['ori_ord'] = '9999999'; assert check(rows) is None
    rows = pair(); rows.append(dict(rows[1])); assert check(rows) is None
    rows = pair(); rows[0]['io_tp_nm'] = '현금매수'; assert check(rows) is None
    rows = pair(); rows[1]['stk_cd'] = 'A114800'; assert check(rows) is None
    assert build_cancel_proof(pair(), original_order_no='123456', code='005930', complete_history=True) is None
    print('13 tests passed')


if __name__ == '__main__':
    test()
